import asyncio
import aiohttp
import time
import random
from typing import Callable, List
from collections import defaultdict
from b_context import BotContext
from c_log import ErrorHandler
from c_utils import PositionUtils
from c_validators import OrderValidator
from d_bapi import BinancePrivateApi

class RiskSet:
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler,
        validate: OrderValidator
    ):
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context
        self.validate = validate

    async def _cancel_risk_order(
        self,
        session,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        cancel_order_by_id: Callable,
        suffix: str
    ) -> bool:
        debug_label = f"[{user_name}][{strategy_name}][{symbol}][{position_side}]"
        pos_data = self.context.position_vars[user_name][strategy_name][symbol][position_side]
        order_id = pos_data.get(f"{suffix}_order_id")

        if not order_id:
            self.error_handler.trades_info_notes(
                f"[INFO]{debug_label}[{suffix.upper()}]: отсутствует ID ордера.", False
            )
            return True  # Считаем успешным, так как отменять нечего

        response = await cancel_order_by_id(
            session=session,
            strategy_name=strategy_name,
            symbol=symbol,
            order_id=order_id,
            suffix=suffix
        )

        if self.validate.validate_cancel_risk_response(response, suffix, debug_label):
            pos_data[f"{suffix}_order_id"] = None
            return True
        return False

    async def _place_risk_order(
        self,
        session,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        suffix: str,
        place_risk_order: Callable,
        offset: float = None,
        activation_percent: float = None,
        is_move_tp: bool = False
    ) -> bool:
        debug_label = f"[{user_name}][{strategy_name}][{symbol}][{position_side}]"
        user_risk_cfg = self.context.total_settings[user_name]["symbols_risk"]
        key = symbol if symbol in user_risk_cfg else "ANY_COINS"

        dinamic_condition_pct = (
            self.context.dinamik_risk_data
            .get(user_name, {})
            .get(symbol, {})
            .get(suffix)
        )

        condition_pct = (
            dinamic_condition_pct
            if dinamic_condition_pct is not None
            else user_risk_cfg.get(key, {}).get(suffix.lower())
        )

        self.error_handler.debug_info_notes(f"[CONFIG][{debug_label}] {suffix.upper()} condition_pct: {condition_pct}")
        if condition_pct is None:
            self.error_handler.debug_info_notes(f"[INFO][{debug_label}] Не задан {suffix.upper()} процент.")
            return True  # Считаем успешным, так как ордер не нужен

        is_long = position_side == "LONG"
        sign = 1 if is_long else -1
        pos_data = self.context.position_vars[user_name][strategy_name][symbol][position_side]
        avg_price = pos_data.get("avg_price")
        qty = pos_data.get("comul_qty")
        price_precision = self.context.position_vars[user_name][strategy_name][symbol].get("price_precision", 2)
        order_type = user_risk_cfg.get(key, {}).get(f"tp_order_type")

        try:
            if suffix.lower() == "sl" and offset:
                target_price = round(avg_price * (1 + sign * offset / 100), price_precision)
                self.error_handler.debug_info_notes(f"[CONFIG][{debug_label}] SL offset: {offset}, target_price: {target_price}")
            elif suffix.lower() == "tp" and is_move_tp:
                shift_pct = activation_percent + condition_pct
                target_price = round(avg_price * (1 + sign * shift_pct / 100), price_precision)
                self.error_handler.debug_info_notes(f"[CONFIG][{debug_label}] TP shift (activation + condition): {shift_pct}, target_price: {target_price}")
            else:
                shift_pct = condition_pct if suffix == "tp" else -abs(condition_pct)
                target_price = round(avg_price * (1 + sign * shift_pct / 100), price_precision)
                self.error_handler.debug_info_notes(f"[CONFIG][{debug_label}] {suffix.upper()} shift_pct: {shift_pct}, target_price: {target_price}")
        except Exception as e:
            self.error_handler.debug_error_notes(f"[ERROR][{debug_label}] Error calculating target_price: {e}")
            return False

        side = "SELL" if is_long else "BUY"
        self.error_handler.debug_info_notes(f"[ORDER][{debug_label}] Placing {suffix.upper()} order: side={side}, qty={qty}, price={target_price}")

        try:
            response = await place_risk_order(
                session=session,
                strategy_name=strategy_name,
                symbol=symbol,
                qty=qty,
                side=side,
                position_side=position_side,
                target_price=target_price,
                suffix=suffix,
                order_type=order_type
            )
        except Exception as e:
            self.error_handler.debug_error_notes(f"[ERROR][{debug_label}] Error placing {suffix.upper()} order: {e}")
            return False

        validated = self.validate.validate_risk_response(response, suffix.upper(), debug_label)
        self.error_handler.debug_info_notes(f"[VALIDATE][{debug_label}] {suffix.upper()} validation result: {validated}")
        if validated:
            success, order_id = validated
            if success:
                pos_data[f"{suffix.lower()}_order_id"] = order_id
                self.error_handler.debug_info_notes(f"[SUCCESS][{debug_label}] {suffix.upper()} order placed: order_id={order_id}")
                return True
        return False

    async def cancel_all_risk_orders(
        self,
        session,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        risk_suffix_list: List,  # ['tp', 'sl']
        cancel_order_by_id: Callable,
    ):
        """
        Отменяет оба ордера (SL и TP) параллельно.
        """
        return await asyncio.gather(*[
            self._cancel_risk_order(
                session,
                user_name,
                strategy_name,
                symbol,
                position_side,
                cancel_order_by_id,
                suffix
            )
            for suffix in risk_suffix_list
        ])

    async def place_all_risk_orders(
        self,
        session,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        risk_suffix_list: List,  # ['tp', 'sl']
        place_risk_order: Callable,
        offset: float = None,
        activation_percent: float = None,
        is_move_tp: bool = False,
    ):
        """
        Размещает оба ордера (SL и TP) параллельно.
        """
        return await asyncio.gather(*[
            self._place_risk_order(
                session,
                user_name,
                strategy_name,
                symbol,
                position_side,
                suffix,
                place_risk_order,
                offset,
                activation_percent,
                is_move_tp
            )
            for suffix in risk_suffix_list
        ])

    async def replace_sl(
        self,
        session: aiohttp.ClientSession,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        is_move_tp: bool,
        offset: float,
        activation_percent: float,
        cancel_order_by_id: Callable,
        place_risk_order: Callable,
        debug_label: str = ""
    ) -> None:
        try:
            cancelled = await self.cancel_all_risk_orders(
                session,
                user_name,
                strategy_name,
                symbol,
                position_side,
                ["tp", "sl"],
                cancel_order_by_id
            )
            self.error_handler.debug_info_notes(f"[CANCEL][{debug_label}] Cancelled SL/TP: {cancelled}")

            risk_suffics_list = ['sl']
            if is_move_tp:
                risk_suffics_list.append('tp')

            placed = await self.place_all_risk_orders(
                session,
                user_name,
                strategy_name,
                symbol,
                position_side,
                risk_suffics_list,
                place_risk_order,
                offset,
                activation_percent,
                is_move_tp
            )
            self.error_handler.debug_info_notes(f"[PLACE][{debug_label}] Placed SL/TP: {placed}")

        except aiohttp.ClientError as e:
            self.error_handler.debug_error_notes(f"[HTTP Error][{debug_label}] Failed to replace SL/TP: {e}")
            raise
        except Exception as e:
            self.error_handler.debug_error_notes(f"[Unexpected Error][{debug_label}] Failed to replace SL/TP: {e}")
            raise

class HandleOrders:
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler,
        pos_utils: PositionUtils,
        risk_set: RiskSet,
        get_hot_price: Callable,
        get_cur_price: Callable
    ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler
        self.pos_utils = pos_utils
        self.get_hot_price = get_hot_price
        self.get_cur_price = get_cur_price
        self.risk_set = risk_set
        self.last_debug_label = {}

    async def set_hedge_mode_for_all_users(self, all_users: List, enable_hedge: bool = True):
        tasks = []
        for user_name in all_users:
            try:
                user_context = self.context.user_contexts[user_name]
                session = user_context["connector"].session
                binance_client: BinancePrivateApi = user_context["binance_client"]
                task = binance_client.set_hedge_mode(
                    session=session, true_hedg=enable_hedge
                )
                tasks.append(task)
            except Exception as e:
                self.error_handler.debug_error_notes(
                    f"[HEDGE_MODE ERROR][{user_name}] → {e}", is_print=True
                )
        await asyncio.gather(*tasks)

    async def _process_user_tasks(self, user_tasks: List[dict]):
        # Извлекаем уникальные символы
        symbols = sorted(set(task["symbol"] for task in user_tasks))
        self.error_handler.debug_info_notes(f"[SYMBOLS] Processing symbols: {symbols}")

        # Обрабатываем каждый символ последовательно с контролем времени
        for symbol in symbols:
            start_time = time.monotonic()  # Замеряем время в начале итерации
            sub_tasks = []
            sync_event = asyncio.Event()  # Для синхронизации LONG/SHORT перед make_order

            # Собираем все задачи для текущего символа
            symbol_tasks = [task for task in user_tasks if task["symbol"] == symbol]
            self.error_handler.debug_info_notes(f"[SYMBOL][{symbol}] Found {len(symbol_tasks)} tasks")

            for task in symbol_tasks:
                action = task["status"]
                position_side = task["position_side"]
                debug_label = task["debug_label"]
                if action == "is_trailing":
                    async def trailing_task(task=task):  # Привязываем task
                        strategy_settings = self.context.strategy_notes[task["strategy_name"]][task["position_side"]]
                        is_move_tp = strategy_settings.get("exit_conditions", {}).get("trailing_sl", {}).get("is_move_tp", False)
                        await self.risk_set.replace_sl(
                            task["client_session"],
                            task["user_name"],
                            task["strategy_name"],
                            task["symbol"],
                            task["position_side"],
                            is_move_tp,
                            task["position_data"].get("offset"),
                            task["position_data"].get("activation_percent"),
                            task["binance_client"].cancel_order_by_id,
                            task["binance_client"].place_risk_order,
                            task["debug_label"]
                        )
                    sub_tasks.append(trailing_task())  # Вызываем корутину
                    continue
                if action == "is_closing":
                    side = "SELL" if position_side == "LONG" else "BUY"
                    qty = task["position_data"].get("comul_qty", 0.0)
                elif action in ["is_opening", "is_avg"]:
                    side = "BUY" if position_side == "LONG" else "SELL"
                    symbols_risk = self.context.total_settings[task["user_name"]]["symbols_risk"]
                    symbol_risk_key = task["symbol"] if task["symbol"] in symbols_risk else "ANY_COINS"
                    leverage = symbols_risk.get(symbol_risk_key, {}).get("leverage", 1)
                    cur_price = None
                    for _ in range(5):
                        cur_price = await self.get_cur_price(
                            session=task["client_session"],
                            ws_price_data=self.context.ws_price_data,
                            symbol=task["symbol"],
                            get_hot_price=self.get_hot_price
                        )
                        if cur_price:
                            break
                        await asyncio.sleep(0.25)
                    if not cur_price:
                        self.error_handler.debug_error_notes(
                            f"[CRITICAL][{debug_label}] не удалось получить цену при выставлении ордера (is_opening, is_avg)."
                        )
                        continue
                    pos_martin = (
                        self.context.position_vars
                        .setdefault(task["user_name"], {})
                        .setdefault(task["strategy_name"], {})
                        .setdefault(task["symbol"], {})
                        .setdefault("martin", {})
                        .setdefault(position_side, {})
                    )
                    base_margin = symbols_risk.get(symbol_risk_key, {}).get("margin_size", 0.0)
                    margin_size = pos_martin.get("cur_margin_size")
                    if margin_size is None:
                        margin_size = base_margin
                    self.error_handler.debug_info_notes(f"{debug_label}: total margin: {margin_size} usdt")
                    qty = self.pos_utils.size_calc(
                        margin_size=margin_size,
                        entry_price=cur_price,
                        leverage=leverage,
                        volume_rate=task["position_data"].get("process_volume"),
                        precision=task["qty_precision"],
                        dubug_label=debug_label
                    )
                else:
                    self.error_handler.debug_info_notes(f"{debug_label} Неизвестный маркер ордера. ")
                    continue
                if not qty or qty <= 0:
                    self.error_handler.debug_info_notes(f"{debug_label} Нулевой размер позиции — пропуск")
                    continue
                async def trade_task(task=task, side=side, qty=qty):  # Привязываем task, side, qty
                    try:
                        user_name = task["user_name"]
                        symbol = task["symbol"]
                        strategy_name = task["strategy_name"]
                        position_side = task["position_side"]
                        debug_label = task["debug_label"]
                        client_session = task["client_session"]
                        binance_client: BinancePrivateApi = task["binance_client"]
                        symbols_risk = self.context.total_settings[user_name]["symbols_risk"]
                        symbol_risk_key = symbol if symbol in symbols_risk else "ANY_COINS"
                        action = task["status"]
                        position_data = task["position_data"]
                        leverage = symbols_risk.get(symbol_risk_key, {}).get("leverage", 1)
                        core = self.context.total_settings.get(user_name, {}).get("core")
                        margin_type = core.get("margin_type", "CROSSED")

                        suffics_list = []
                        if bool(symbols_risk.get(symbol_risk_key, {}).get("sl")):
                            suffics_list.append("sl")
                        if bool(symbols_risk.get(symbol_risk_key, {}).get("tp")):
                            suffics_list.append("tp")

                        last_known_label = self.last_debug_label \
                            .setdefault(user_name, {}) \
                            .setdefault(symbol, {}) \
                            .setdefault(position_side, None)
                        pos = self.context.position_vars.get(user_name, {}) \
                            .get(strategy_name, {}) \
                            .get(symbol, {}) \
                            .get(position_side)
                        in_position = pos and pos.get("in_position")
                        if action == "is_closing":
                            if not in_position:
                                return
                        elif action == "is_opening":
                            if in_position:
                                return
                        if debug_label != last_known_label:
                            await binance_client.set_margin_type(client_session, strategy_name, symbol, margin_type)
                            await binance_client.set_leverage(client_session, strategy_name, symbol, leverage)
                            self.last_debug_label[user_name][symbol][position_side] = debug_label
                        last_avg_price = pos.get("avg_price", None) if pos else None
                        # Синхронизация перед make_order
                        self.error_handler.debug_info_notes(f"[SYNC][{debug_label}] Waiting for sync before make_order")
                        await sync_event.wait()
                        order_start_time = time.monotonic()
                        self.error_handler.debug_info_notes(f"[ORDER][{debug_label}] Starting make_order at {order_start_time:.2f}s")
                        market_order_result = await binance_client.make_order(
                            session=client_session,
                            strategy_name=strategy_name,
                            symbol=symbol,  # Добавляем symbol
                            qty=qty,
                            side=side,
                            position_side=position_side,
                            market_type="MARKET"
                        )
                        order_end_time = time.monotonic()
                        self.error_handler.debug_info_notes(f"[ORDER][{debug_label}] Completed make_order in {order_end_time - order_start_time:.2f}s")
                        success, validated = self.risk_set.validate.validate_market_response(
                            market_order_result[0], debug_label
                        )
                        if not success and action == "is_opening":
                            self.error_handler.debug_info_notes(
                                f"[INFO][{debug_label}] не удалось нормально открыть позицию.", is_print=True
                            )
                            return
                        if action in {"is_avg", "is_closing"}:
                            position_data["trailing_sl_progress_counter"] = 0
                            for attempt in range(2):
                                cancelled = await self.risk_set.cancel_all_risk_orders(
                                    session=client_session,
                                    user_name=user_name,
                                    strategy_name=strategy_name,
                                    symbol=symbol,
                                    position_side=position_side,
                                    risk_suffix_list=suffics_list,
                                    cancel_order_by_id=binance_client.cancel_order_by_id
                                )
                                if all(x is not False for x in cancelled):
                                    self.error_handler.debug_info_notes(
                                        f"[CANCEL][{user_name}][{strategy_name}][{symbol}][{position_side}] All risk orders cancelled on attempt {attempt + 1}"
                                    )
                                    break
                                await asyncio.sleep(0.15)
                            else:
                                self.error_handler.debug_error_notes(
                                    f"[INFO][{debug_label}] не удалось отменить риск ордера после 2-х попыток"
                                )
                                return
                        if action == "is_closing":
                            return
                        if action in {"is_opening", "is_avg"}:
                            for attempt in range(120):
                                pos_data = self.context.position_vars.get(user_name, {}) \
                                    .get(strategy_name, {}) \
                                    .get(symbol, {}) \
                                    .get(position_side, {})
                                avg_price = pos_data.get("avg_price")
                                in_position = pos_data.get("in_position")
                                if in_position and avg_price != last_avg_price and avg_price is not None:
                                    self.error_handler.debug_info_notes(
                                        f"[READY][{debug_label}] pos_data обновлены на попытке {attempt+1}: "
                                        f"avg_price={avg_price}, in_position={in_position}"
                                    )
                                    break
                                await asyncio.sleep(0.15)
                            else:
                                self.error_handler.debug_error_notes(
                                    f"[TIMEOUT][{debug_label}] не удалось дождаться avg_price/in_position "
                                    f"(avg_price={avg_price}, in_position={in_position})"
                                )
                                return
                        for attempt in range(2):
                            placed = await self.risk_set.cancel_all_risk_orders(
                                session=client_session,
                                user_name=user_name,
                                strategy_name=strategy_name,
                                symbol=symbol,
                                position_side=position_side,
                                risk_suffix_list=suffics_list,
                                cancel_order_by_id=binance_client.cancel_order_by_id
                            )
                            if all(x is not False for x in placed):
                                self.error_handler.debug_info_notes(
                                    f"[CANCEL][{user_name}][{strategy_name}][{symbol}][{position_side}] All risk orders cancelled on attempt {attempt + 1}"
                                )
                                break
                            await asyncio.sleep(0.15)
                        else:
                            self.error_handler.debug_error_notes(
                                f"[INFO][{debug_label}] не удалось отменить риск ордера после 2-х попыток"
                            )
                            return
                        for attempt in range(2):
                            placed = await self.risk_set.place_all_risk_orders(
                                session=client_session,
                                user_name=user_name,
                                strategy_name=strategy_name,
                                symbol=symbol,
                                position_side=position_side,
                                risk_suffix_list=suffics_list,
                                place_risk_order=binance_client.place_risk_order
                            )
                            if all(x is not False for x in placed):
                                self.error_handler.debug_info_notes(
                                    f"[PLACE][{user_name}][{strategy_name}][{symbol}][{position_side}] All risk orders placed on attempt {attempt + 1}"
                                )
                                break
                            await asyncio.sleep(0.15)
                        else:
                            self.error_handler.debug_error_notes(
                                f"[CRITICAL][{debug_label}] не удалось установить риск ордера после 2-х попыток."
                            )
                    except Exception as e:
                        self.error_handler.debug_error_notes(
                            f"[Order Error] {task['debug_label']} → {e}", is_print=True
                        )
                sub_tasks.append(trade_task())  # Вызываем корутину
            try:
                if sub_tasks:
                    self.error_handler.debug_info_notes(f"[PARALLEL][{symbol}] Starting tasks: {len(sub_tasks)} tasks, tasks: {[type(t).__name__ for t in sub_tasks]}")
                    sync_event.set()  # Разрешаем задачам двигаться к make_order
                    await asyncio.gather(*sub_tasks)
            except Exception as e:
                self.error_handler.debug_error_notes(
                    f"[compose_trade_instruction] Ошибка при выполнении задач для {symbol}: {e}", is_print=True
                )
            # Контроль времени итерации
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            target_time = random.uniform(1.0, 1.5)  # Случайная цель 1–1.5с
            if elapsed_time < target_time:
                sleep_time = target_time - elapsed_time
                self.error_handler.debug_info_notes(
                    f"[TIMING][{symbol}] Итерация заняла {elapsed_time:.2f}s, спим {sleep_time:.2f}s для достижения {target_time:.2f}s"
                )
                await asyncio.sleep(sleep_time)

    async def compose_trade_instruction(self, task_list: list[dict]):
        # Группировка задач по юзерам
        user_groups = defaultdict(list)
        for task in task_list:
            user_groups[task["user_name"]].append(task)

        # Запускаем обработку каждого юзера параллельно
        user_tasks = [self._process_user_tasks(tasks) for tasks in user_groups.values()]
        await asyncio.gather(*user_tasks)