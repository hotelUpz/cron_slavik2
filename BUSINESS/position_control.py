import aiohttp
import asyncio
import time
import copy
from pprint import pprint
from typing import Callable, Dict, List, Set
from collections.abc import Awaitable
from b_context import BotContext
from c_log import ErrorHandler
from c_utils import format_msg, format_duration, to_human_digit, milliseconds_to_datetime
from d_bapi import BinancePrivateApi
from c_validators import OrderValidator 
from MANAGERS.online import NetworkManager


class PositionCleaner():
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler,
        set_pos_defaults: Callable,
        preform_message: Callable,    
    ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler
        self.set_pos_defaults = set_pos_defaults
        self.preform_message = preform_message
        self.validate = OrderValidator(error_handler=error_handler)

    async def pnl_report(
            self,
            user_name: str,
            strategy_name: str,
            symbol: str,
            pos_side: str,
            get_realized_pnl: Callable
        ):
        """
        Отчет по реализованному PnL для Binance (через API),
        без использования текущей цены.
        """
        debug_label = f"{user_name}_{symbol}_{pos_side}"
        cur_time = int(time.time() * 1000)
        pos_data = (
            self.context.position_vars
            .get(user_name, {})
            .get(strategy_name, {})
            .get(symbol, {})
            .get(pos_side, {})
        )

        start_time = pos_data.get("c_time")  # время открытия позиции
        notional = pos_data.get("notional")
        pnl_usdt, commission = 0.0, 0.0

        try:
            pnl_usdt, commission = await get_realized_pnl(
                symbol=symbol,
                direction=pos_side.upper(),
                start_time=start_time,
                end_time=cur_time
            )
            # print(pnl_usdt, commission)
        except:
            self.error_handler.debug_error_notes(f"[{debug_label}]: ошибка при расчете пнл.")
            return

        if pnl_usdt is None:
            self.error_handler.debug_error_notes(f"[{debug_label}]: ошибка при расчете pnl_usdt.")
            return

        pnl_pct = (pnl_usdt / notional) * 100
        time_in_deal = cur_time - start_time if start_time else None

        body = {
            "user_name": user_name,
            "symbol": symbol,
            "pos_side": pos_side,
            "pnl_usdt": pnl_usdt,
            "pnl_pct": pnl_pct,
            "commission": commission,
            "cur_time": cur_time,
            "time_in_deal": format_duration(time_in_deal)
        }

        self.preform_message(
            marker="report",
            body=body,
            is_print=True
        )

        return pnl_usdt

    def reset_necessary_state(self, user_name, strategy_name, symbol, position_side):
        self.context.position_vars[user_name][strategy_name][symbol][position_side].update(
            {   
                "offset": 0.0,
                "activation_percent": 0.0,
                "process_volume": 0.0
            }
        )
    
    @staticmethod
    def reset_symbols_prison(strategy_data: dict):
        """
        Сброс всех sets symbols_prison для LONG и SHORT в указанной стратегии пользователя.
        """
        for symbol, pos_data in strategy_data.items():
            for side in ("LONG", "SHORT"):
                if side in pos_data and isinstance(pos_data[side], dict):
                    pos_data[side]["symbols_prison"] = set()

    def reset_position_vars(
            self,
            user_name,
            strategy_name,
            symbol,
            position_side                    
        ):

        # ♻️ Переинициализация текущей позиции
        symbol_data = self.context.position_vars[user_name][strategy_name].setdefault(symbol, {})
        self.set_pos_defaults(symbol_data, symbol, position_side)

        # 🧹 Обнуляем current price
        self.context.ws_price_data[symbol] = {"close": None}

        # 🧼 Глобальный сброс symbols_prison для всех позиций данной стратегии данного юзера
        self.reset_symbols_prison(self.context.position_vars[user_name][strategy_name])

        # Очистка кэша антидвойного закрытия
        for action in ["is_sl", "is_tp"]:
            unik_closing_key = f"{user_name}_{strategy_name}_{symbol}_{position_side}_{action}"
            self.context.anti_double_close[unik_closing_key] = False

    async def close_position_cleanup(
            self,
            session,
            user_name,
            strategy_name,
            symbol,
            position_side,
            cancel_order_by_id: Callable,
            cancel_all_risk_orders: Callable,
            get_realized_pnl: Callable
        ):

        pnl_val = await self.pnl_report(
            user_name=user_name,
            strategy_name=strategy_name,
            symbol=symbol,
            pos_side=position_side,
            get_realized_pnl=get_realized_pnl
        )

        # --------- MARTIL GALE LOGIC -------------
        symbols_risk = self.context.total_settings[user_name]["symbols_risk"]
        symbol_key = symbol if symbol in symbols_risk else "ANY_COINS"
        sbl_risk = symbols_risk[symbol_key]

        if sbl_risk.get("is_martin") and pnl_val is not None:
            # Создаем вложенные словари один раз
            pos_martin = (
                self.context.position_vars
                    .setdefault(user_name, {})
                    .setdefault(strategy_name, {})
                    .setdefault(symbol, {})
                    .setdefault("martin", {})
                    .setdefault(position_side, {})
            )

            martin_multipliter = sbl_risk.get("martin_multipliter", 1)
            base_margin = sbl_risk["margin_size"]

            if pnl_val > 0:
                pos_martin.update({
                    "success": 1,
                    "cur_margin_size": base_margin,
                })
            elif pnl_val < 0:
                cur_margin = pos_martin.get("cur_margin_size", base_margin)
                pos_martin.update({
                    "success": -1,
                    "cur_margin_size": cur_margin * martin_multipliter,
                })     

        # 🚫 Отменяем TP и SL
        await cancel_all_risk_orders(
                session,
                user_name,
                strategy_name,
                symbol,
                position_side,
                ["tp", "sl"],
                cancel_order_by_id
            )

class PositionsUpdater(PositionCleaner):
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler,
        set_pos_defaults: Callable,
        preform_message: Callable
    ):
        super().__init__(context, error_handler, set_pos_defaults, preform_message)        
    
    @staticmethod
    def unpack_position_info(position: dict) -> dict:
        if not isinstance(position, dict):
            return {
                "symbol": "",
                "side": "",
                "amount": 0.0,
                "entry_price": 0.0,
                "notional": 0.0,        # добавил
                "leverage": 0.0,        # добавил
                "margin": 0.0           # добавил
            }

        return {
            "symbol": position.get("symbol", "").upper(),
            "side": position.get("positionSide", "").upper(),
            "amount": abs(float(position.get("positionAmt", 0.0))),
            "entry_price": float(position.get("entryPrice", 0.0)),
            "notional": abs(float(position.get("notional", 0.0))),          # USDT размер позиции
            "leverage": float(position.get("leverage", 0.0)),          # плечо
            "margin": float(position.get("isolatedMargin", 0.0))       # маржа (если isolated)
        }      

    async def update_positions(
        self,  
        session,      
        user_name: str,
        strategy_name: str,
        target_symbols: Set[str],
        positions: List[Dict],
        cancel_order_by_id: Callable,        
        cancel_all_risk_orders: Callable,
        get_realized_pnl: Callable,
        make_order: Callable
    ) -> None:
        """
        Обновляет данные о позициях для указанной стратегии и символов.
        """
        try:
            filtered_positions = [
                pos for pos in positions
                if pos and pos.get("symbol", "").upper() in target_symbols
            ]
            strategy_positions = self.context.position_vars[user_name][strategy_name]

            for position in filtered_positions:
                info = self.unpack_position_info(position)

                symbol = info.get("symbol", "")
                position_side = info.get("side", "")
                position_amt = info.get("amount", 0.0)
                entry_price = info.get("entry_price", 0.0)
                notional = info.get("notional", 0.0)
                cur_time = int(time.time()* 1000)

                debug_label = f"{user_name}_{strategy_name}_{symbol}_{position_side}"
                
                if not strategy_positions.get(symbol, {}).get(position_side):
                    self.error_handler.debug_info_notes(f"No data for {debug_label}, skipping")
                    continue

                symbol_data = strategy_positions[symbol][position_side]

                is_partly_closed = False
                success_closed = False
                if position_amt > 0:    
                    old_amt = symbol_data.get("comul_qty")  
                    if old_amt and position_amt < old_amt / 4:                        
                        symbol_data.update({"comul_qty": position_amt})
                        is_partly_closed = True
                    else:
                        if not symbol_data.get("problem_closed"):
                            self.reset_necessary_state(user_name, strategy_name, symbol, position_side)
                            entry_price_struc = symbol_data.get("entry_price")
                            in_position = symbol_data.get("in_position")
                            cur_time_struc = symbol_data.get("c_time")
                            notional_struc = symbol_data.get("notional")
                            
                            symbol_data.update({
                                "in_position": True,
                                "comul_qty": position_amt,
                                "notional": notional if not in_position else notional_struc,
                                "entry_price": entry_price if not in_position else entry_price_struc,
                                "avg_price": entry_price,
                                "c_time": cur_time if not in_position else cur_time_struc,
                            })

                if is_partly_closed:                 
                    # Основной запрос на маркет-ордер
                    market_order_result = await make_order(
                        session=session,
                        strategy_name=strategy_name,
                        symbol=symbol,
                        qty=symbol_data.get("comul_qty"),
                        side="SELL" if position_side == "LONG" else "BUY",
                        position_side=position_side,
                        market_type="MARKET"
                    )

                    success_closed, validated = self.validate.validate_market_response(
                        market_order_result[0], debug_label
                    )
                    if not success_closed:
                        symbol_data.update({"problem_closed": True})
                        self.error_handler.debug_info_notes(
                            f"[INFO][{debug_label}] не удалось полностью закрыть остаток позиции.",
                            is_print=True
                        )

                if not position_amt or success_closed:
                    if symbol_data["in_position"]:
                        # Сперва отменяем риск ордера
                        await self.close_position_cleanup(               
                            session,
                            user_name,
                            strategy_name,
                            symbol,
                            position_side,
                            cancel_order_by_id,
                            cancel_all_risk_orders,
                            get_realized_pnl
                        )
                        # Затем очищаем кеш контроля позиций
                        self.reset_position_vars(user_name, strategy_name, symbol, position_side)

            self.context.first_update_done[user_name] = True
            # print("jdjdjdj")
        except KeyError as e:
            self.error_handler.debug_error_notes(f"{debug_label}[Key Error] Invalid position data for {strategy_name}: {e}")
            return
        except Exception as e:
            self.error_handler.debug_error_notes(f"{debug_label}[Unexpected Error] Failed to update positions for {strategy_name}: {e}")
            return        

    async def refresh_positions_state(
        self,
        session: aiohttp.ClientSession,
        user_name: str,
        fetch_positions: Callable[[aiohttp.ClientSession], Awaitable[Dict]],
        cancel_order_by_id: Callable,
        cancel_all_risk_orders: Callable,
        get_realized_pnl: Callable,
        make_order: Callable
    ) -> None:
        """
        Обновляет состояние позиций для всех стратегий последовательно.
        """
        # print("refresh_positions_state1")
        debug_label = f"[{user_name}]"        
        try:
            positions = await fetch_positions(session)
            positions = positions.get("positions", [])      
            # print(positions)   
            # 
            # pprint(positions)
            if not positions:
                return            

            # Параллельная обработка всех стратегий пользователя
            await asyncio.gather(*[
                self.update_positions(
                    session,
                    user_name,
                    strategy_name,
                    strategy_details.get("symbols", set()),
                    positions,
                    cancel_order_by_id,
                    cancel_all_risk_orders,
                    get_realized_pnl,
                    make_order
                )
                for strategy_name, strategy_details in self.context.total_settings[user_name].get("strategies_symbols", {}).items()
            ])

        except aiohttp.ClientError as e:
            self.error_handler.debug_error_notes(f"{debug_label}[HTTP Error] Failed to fetch positions: {e}. ")
            raise
        except Exception as e:
            self.error_handler.debug_error_notes(f"{debug_label}[Unexpected Error] Failed to refresh positions: {e}. ")
            raise

class Sync(PositionsUpdater):
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler,        
        loaded_cache: dict,
        write_cache: Callable,
        set_pos_defaults: Callable, 
        cancel_all_risk_orders: Callable,   
        preform_message: Callable,  
        use_cache: bool,
        positions_update_frequency: int = 1
    ):
        super().__init__(
            context,
            error_handler,
            set_pos_defaults,
            preform_message
        )
        self.loaded_cache = loaded_cache
        self.use_cache = use_cache
        self.positions_update_frequency = positions_update_frequency
        self.cancel_all_risk_orders = cancel_all_risk_orders
        self.write_cache = write_cache
        self._pos_lock = asyncio.Lock()        

    def sync_cache_with_positions(self, user_name):
        """Merge cached values into existing context.position_vars in-place."""
        user_cache = self.loaded_cache.get(user_name)
        if not user_cache:
            return

        user_positions = self.context.position_vars.setdefault(user_name, {})

        for strategy_name, cached_symbols in user_cache.items():
            if not isinstance(cached_symbols, dict):
                continue
            # получаем/создаём словарь позиций для стратегии
            strategy_positions = user_positions.setdefault(strategy_name, {})

            for symbol, cached_data in cached_symbols.items():
                if not isinstance(cached_data, dict):
                    continue

                if symbol in strategy_positions and isinstance(strategy_positions[symbol], dict):
                    strategy_positions[symbol].update(copy.deepcopy(cached_data))
                else:
                    # создаём новый dict (копия)
                    strategy_positions[symbol] = copy.deepcopy(cached_data)

    async def sync_pos_all_users(self, user_name: str):
        # print("sync_pos_all_users1")
        connector: NetworkManager = self.context.user_contexts[user_name]["connector"]
        binance_client: BinancePrivateApi = self.context.user_contexts[user_name]["binance_client"]       

        await self.refresh_positions_state(
            session=connector.session,
            user_name=user_name,
            fetch_positions=binance_client.fetch_positions,
            cancel_order_by_id=binance_client.cancel_order_by_id,
            cancel_all_risk_orders=self.cancel_all_risk_orders,
            get_realized_pnl=binance_client.get_realized_pnl,
            make_order=binance_client.make_order
        )   

    async def positions_flow_manager(self):
        """Цикл обновления позиций и синхронизации кэша"""

        all_users = list(self.context.total_settings.keys())
        # print(all_users)
        if self.use_cache and self.context.first_iter and self.loaded_cache:
            for user_name in all_users:
                self.sync_cache_with_positions(user_name)
            self.loaded_cache = None
        
        # print("pos_vars: \n")
        # pprint(self.context.position_vars)

        cache_update_interval = 5.0
        last_cache_time = time.monotonic()        

        while not self.context.stop_bot:
            await asyncio.sleep(self.positions_update_frequency)

            try:
                await asyncio.gather(*[self.sync_pos_all_users(user_name) for user_name in all_users])
            except Exception as e:
                print(f"[SYNC][ERROR] refresh_positions_state: {e}")

            now = time.monotonic()

            if self.use_cache and (now - last_cache_time >= cache_update_interval):
                try:
                    # берем снимок состояния под локом, чтобы не сериализовать "плавающие" объекты
                    async with self._pos_lock:
                        snapshot = copy.deepcopy(self.context.position_vars)
                    # запись — предполагается, что self.write_cache асинхронен
                    await self.write_cache(
                        data_dict=snapshot,
                        file_name="pos_cache.pkl"
                    )
                except Exception as e:
                    print(f"[SYNC][ERROR] write_cache: {e}")
                last_cache_time = now