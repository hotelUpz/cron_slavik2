import aiohttp
from typing import Dict, Tuple, Callable, Optional
from b_context import BotContext
from c_log import ErrorHandler, log_time
from c_utils import PositionUtils
from d_bapi import BinancePrivateApi
# from .patterns import RiskSet


class TrailingSL:
    def __init__(
        self,
        context: BotContext,
        error_handler: ErrorHandler
    ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler

    def trailing_sl_control(
        self,
        trailing_sl: list,
        trailing_sl_progress_counter: int,
        nPnl: float,
        debug_label: str
    ) -> Tuple[int, float]:
        
        debug_label = f"{debug_label}[TR_SL]"

        if not trailing_sl or not isinstance(trailing_sl, list):
            self.error_handler.debug_info_notes(f"{debug_label} Невалидный trailing_sl: ожидался список.")
            return trailing_sl_progress_counter, 0.0

        if not isinstance(nPnl, (int, float)):
            self.error_handler.debug_info_notes(f"{debug_label} Некорректный nPnl: {nPnl}")
            return trailing_sl_progress_counter, 0.0

        tr_sl_counter = min(trailing_sl_progress_counter, len(trailing_sl) - 1)
        current_step = trailing_sl[tr_sl_counter]
        activation_percent = current_step.get('activation_indent', 0.0)
        offset_percent = current_step.get('offset_indent', 0.0)

        if trailing_sl_progress_counter >= len(trailing_sl):
            return trailing_sl_progress_counter, offset_percent

        if nPnl >= activation_percent:
            trailing_sl_progress_counter += 1
            self.error_handler.debug_info_notes(
                f"{debug_label} Прогресс: {tr_sl_counter} → {trailing_sl_progress_counter}, nPnl={nPnl}, activation={activation_percent}"
            )

        return trailing_sl_progress_counter, offset_percent, activation_percent

    def check_trailing_sl_and_report(
        self,
        nPnl: float,
        normalized_sign: int,
        settings_pos_options: dict,
        symbol_data: Dict,
        debug_label: str
    ) -> bool:

        trailing_settings = settings_pos_options.get("exit_conditions", {}).get("trailing_sl", {})

        if not trailing_settings.get("enable", False):
            return

        trailing_sl = trailing_settings.get("val", [])

        progress_counter = symbol_data.get("trailing_sl_progress_counter", 0)
        new_progress_counter, offset, activation_percent = self.trailing_sl_control(
            trailing_sl,
            progress_counter,
            nPnl * normalized_sign,
            debug_label
        )

        if new_progress_counter != progress_counter:
            symbol_data["trailing_sl_progress_counter"] = new_progress_counter
            self.error_handler.trades_info_notes(
                f"🛡️ {debug_label} Трейлинг-стоп сдвинут. Счетчик: {new_progress_counter}"
            )
            symbol_data["is_trailing"] = True
            symbol_data["offset"] = offset
            symbol_data["activation_percent"] = activation_percent

            return True 
        
        return False


class TP:
    def __init__(
            self,
            context: BotContext,
            error_handler: ErrorHandler
        ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler

    def tp_control(self, tp: float, nPnl: float, debug_label: str) -> bool:
        """
        Контроль тейк-профита с валидацией входных данных.
        """
        if not isinstance(tp, (int, float)) or not isinstance(nPnl, (int, float)):
            self.error_handler.debug_info_notes(
                f"{debug_label}[TP_CONTROL] Невалидные типы: ({type(tp)}), ({type(nPnl)})"
            )
            return False

        return nPnl >= tp

    def check_tp(
        self,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        nPnl: float,
        normalized_sign: int,
        symbols_risk: dict,
        debug_label: str
        
    ) -> Optional[bool]:
        """
        Проверяет условия для тейк-профита и при необходимости инициирует сигнал закрытия позиции.
        """
        key_symb = "ANY_COINS" if symbol not in symbols_risk else symbol

        dinamic_tp = (
            self.context.dinamik_risk_data
                .get(user_name, {})
                .get(symbol, {})
                .get("tp")
        )

        take_profit = (
            dinamic_tp
            if dinamic_tp is not None
            else symbols_risk.get(key_symb, {}).get("fallback_tp")
        )

        if take_profit is None:
            return None

        # Применяем нормализованный знак на PnL
        signed_nPnl = nPnl * normalized_sign

        if not self.tp_control(take_profit, signed_nPnl, debug_label):
            return None

        # Логируем действие
        self.error_handler.trades_info_notes(
            f"[{user_name}][{strategy_name}][{symbol}][{position_side}]. '🏆 Закрываем позицию по резервному тейк-профиту.'. ",
            True
        )

        return True
    
class SL:
    def __init__(
            self,
            context: BotContext,
            error_handler: ErrorHandler
        ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler     

    def stop_loss_control(
        self,
        stop_loss: float,
        nPnl: float,
        trailing_sl_progress_counter: int,
        debug_label: str
    ) -> bool:
        """
        Контроль стоп-лосса:
        - Не срабатывает, если активен трейлинг-стоп (progress > 0)
        - Срабатывает при достижении PnL уровня SL
        """
        if not isinstance(stop_loss, (int, float)) or not isinstance(nPnl, (int, float)):
            self.error_handler.debug_info_notes(
                f"{debug_label}[SL_CONTROL] Невалидные типы: stop_loss={type(stop_loss)}, nPnl={type(nPnl)}"
            )
            return False

        if trailing_sl_progress_counter > 0:
            self.error_handler.debug_info_notes(f"{debug_label}[SL_CONTROL] Пропущен: активен трейлинг-стоп")
            return False

        return nPnl <= stop_loss

    def check_sl(
        self,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        nPnl: float,
        normalized_sign: int,
        trailing_sl_progress_counter: int,        
        symbols_risk: dict,
        debug_label: str

    ) -> Optional[bool]:
        """
        Проверяет условия для SL и инициирует сигнал, если необходимо.
        """
        key_symb = "ANY_COINS" if symbol not in symbols_risk else symbol

        dinamic_sl = (
            self.context.dinamik_risk_data
                .get(user_name, {})
                .get(symbol, {})
                .get("sl")
        )

        stop_loss = (
            dinamic_sl
            if dinamic_sl is not None
            else symbols_risk.get(key_symb, {}).get("sl")
        )

        if stop_loss is None:
            return None
        
        signed_nPnl = nPnl * normalized_sign

        if not self.stop_loss_control(stop_loss, signed_nPnl, trailing_sl_progress_counter, debug_label):
            return None

        unique_key = f"{user_name}_{strategy_name}_{symbol}_{position_side}_is_sl"
        if self.context.anti_double_close.get(unique_key, False):
            return None

        self.context.anti_double_close[unique_key] = True

        # Логируем действие
        self.error_handler.trades_info_notes(
            f"[{debug_label}]. '❌ Закрываем позицию по стоп-лоссу.'. ",
            True
        )

        return True
    
    
class SignalExit:
    def __init__(
            self,
            context: BotContext,
            error_handler: ErrorHandler
        ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler

    def check_signal_exit(
        self,
        close_signal: bool,
        cur_nPnl: float,
        normalized_sign: int,
        settings_pos_options: dict,
        debug_label: str
    ) -> bool:
        """Проверка на закрытие позиции по сигналу, с учётом минимального профита."""
        signal_cfg = settings_pos_options.get("exit_conditions", {}).get("close_by_signal", {})
        if not (signal_cfg.get("is_active") and close_signal):
            return False

        min_profit = signal_cfg.get("min_profit")
        if min_profit is not None and (cur_nPnl * normalized_sign) < min_profit:
            return False

        self.error_handler.trades_info_notes(
            f"[{debug_label}]. '🏁 Закрываем позицию по сигналу.'. ",
            True
        )

        return True
    
        
class Average:
    def __init__(
            self,
            context: BotContext,
            error_handler: ErrorHandler,
        ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler

    def avg_control(
        self,
        grid_orders: list,
        avg_progress_counter: int,
        cur_price: float,
        init_price: float,
        normalized_sign: int,
        nPnL_calc: Callable[[float, float, str], float],
        avg_signal: bool,
        debug_label: str,
    ) -> tuple[int, float]:
        """
        Контроль усреднения.
        Возвращает:
            - обновлённый прогресс (int),
            - объём текущего шага (float), либо 0.0 если усреднение не нужно.
        """
        if not grid_orders or not isinstance(grid_orders, list):
            self.error_handler.debug_info_notes(f"{debug_label} Невалидный grid_orders: ожидался список.")
            return avg_progress_counter, 0.0

        if not isinstance(avg_progress_counter, int) or avg_progress_counter < 0:
            self.error_handler.debug_info_notes(f"{debug_label} Некорректный avg_progress_counter: {avg_progress_counter}")
            return avg_progress_counter, 0.0

        len_grid_orders = len(grid_orders)

        if len_grid_orders <= 1 or avg_progress_counter >= len_grid_orders:
            return avg_progress_counter, 0.0

        step = grid_orders[min(avg_progress_counter, len_grid_orders - 1)]
        indent = -abs(step.get("indent", 0.0))
        volume = step.get("volume", 0.0)

        avg_nPnl = nPnL_calc(cur_price, init_price, debug_label) * normalized_sign

        if avg_nPnl <= indent:
            new_progress = avg_progress_counter + 1

            # ограничим, чтобы не выйти за пределы
            grid_index = min(new_progress, len_grid_orders-1)
            open_by_signal = grid_orders[grid_index].get("signal", False)

            if not open_by_signal or avg_signal:
                return new_progress, volume

        return avg_progress_counter, 0.0

    def check_avg_and_report(
        self,
        cur_price: float,
        symbol_data: dict,
        nPnL_calc: Callable[[float, float, str], float],
        normalized_sign: int,
        avg_signal: bool,
        settings_pos_options: Dict,
        debug_label: str,
    ) -> bool:
        """Проверяет необходимость усреднения и формирует сигнал."""
        grid_cfg = settings_pos_options["entry_conditions"]["grid_orders"]
        cur_avg_progress = symbol_data.get("avg_progress_counter", 1)
        init_price = symbol_data.get("entry_price", 0.0)

        new_avg_progress, avg_volume = self.avg_control(
            grid_cfg,
            cur_avg_progress,
            cur_price,
            init_price,
            normalized_sign,
            nPnL_calc,
            avg_signal,
            debug_label,
        )

        if new_avg_progress == cur_avg_progress or avg_volume == 0.0:
            return False

        symbol_data["avg_progress_counter"] = new_avg_progress
        symbol_data["process_volume"] = avg_volume / 100

        safe_idx = min(new_avg_progress-1, len(grid_cfg) - 1)
        self.error_handler.trades_info_notes(
            f"[{debug_label}] ➗ Усредняем. "
            f"Счётчик {cur_avg_progress} → {new_avg_progress}. "
            f"Cur vol: {avg_volume} "
            f"Cur price: {cur_price} "
            f"Indent: {grid_cfg[safe_idx]}",
            True,
        )
        return True


class RiskOrdersControl:
    """Управляет рисками и мониторингом позиций для торговых стратегий."""

    def __init__(
            self,
            context: BotContext,
            error_handler: ErrorHandler,
            pos_utils: PositionUtils
        ):
        error_handler.wrap_foreign_methods(self)
        self.context = context
        self.error_handler = error_handler
        self.pos_utils = pos_utils

        self.trailing_sl_control = TrailingSL(
            context=context,
            error_handler=error_handler
        )

        self.signal_exit_control = SignalExit(
            context=context,
            error_handler=error_handler
        )

        self.avg_control = Average(
            context=context,
            error_handler=error_handler
        )

        self.sl_control = SL(
            context=context,
            error_handler=error_handler
        )

        self.tp_control = TP(
            context=context,
            error_handler=error_handler
        )

    def risk_symbol_monitoring(
        self,
        user_name: str,
        strategy_name: str,
        symbol: str,
        position_side: str,
        avg_signal: bool,
        close_signal: bool,
        compose_signals: Callable,
        client_session: Optional[aiohttp.ClientSession],
        binance_client: BinancePrivateApi
    ) -> dict:
        """
        Мониторит позицию и управляет рисками (стоп-лосс, тейк-профит, трейлинг-стоп, усреднение).
        Возвращает словарь с результатами.
        """

        debug_label = f"[{user_name}][{strategy_name}][{symbol}][{position_side}]"
        symbol_data = self.context.position_vars[user_name][strategy_name][symbol]
        symbol_position_data = symbol_data[position_side]
        symbols_risk = self.context.total_settings[user_name]["symbols_risk"]
        settings_pos_options = self.context.strategy_notes[strategy_name][position_side]

        try:
            if not symbol_position_data:
                self.error_handler.debug_error_notes(f"No position data for {debug_label}")
                return
            
            if not symbol_position_data.get("in_position"):
                return

            normalized_sign = {"LONG": 1, "SHORT": -1}.get(position_side)
            if normalized_sign is None:
                self.error_handler.debug_error_notes(f"Invalid position_side {debug_label}")
                return

            avg_price = symbol_position_data.get("avg_price", 0.0)
            if not avg_price:
                # self.error_handler.debug_info_notes(f"Invalid avg_price for {debug_label}.")
                return

            cur_price = self.context.ws_price_data.get(symbol, {}).get("close")
            if cur_price is None or cur_price == 0:
                # self.error_handler.debug_error_notes(f"Failed to get price for {debug_label}")
                return

            cur_nPnl = self.pos_utils.nPnL_calc(
                cur_price,
                avg_price,
                debug_label,
            )
            if cur_nPnl is None:
                return
            
            # print(f"{debug_label}: nPnl: {cur_nPnl}")

            tp_result = self.tp_control.check_tp(
                user_name=user_name,
                strategy_name=strategy_name,
                symbol=symbol,
                position_side=position_side,
                nPnl=cur_nPnl,
                normalized_sign=normalized_sign,
                symbols_risk=symbols_risk,
                debug_label=debug_label
            )
            
            if tp_result and not symbol_position_data.get("is_tp"):
                symbol_position_data["is_tp"] = True
                return compose_signals(user_name, strategy_name, symbol, position_side, "is_closing", client_session, binance_client)

            # trailing_result = self.trailing_sl_control.check_trailing_sl_and_report(
            #     nPnl=cur_nPnl,
            #     normalized_sign=normalized_sign,
            #     settings_pos_options=settings_pos_options,
            #     symbol_data=symbol_position_data,
            #     debug_label=debug_label
            # )

            # if trailing_result:
            #     return compose_signals(user_name, strategy_name, symbol, position_side, "is_trailing", client_session, binance_client)

            # sl_result = self.sl_control.check_sl(
            #     user_name=user_name,
            #     strategy_name=strategy_name,
            #     symbol=symbol,
            #     position_side=position_side,
            #     nPnl=cur_nPnl,
            #     normalized_sign=normalized_sign,
            #     trailing_sl_progress_counter=symbol_position_data.get("trailing_sl_progress_counter", 0),
            #     symbols_risk=symbols_risk,
            #     debug_label=debug_label
            # )

            # if sl_result and not symbol_position_data.get("is_sl"):
            #     symbol_position_data["is_sl"] = True
            #     return compose_signals(user_name, strategy_name, symbol, position_side, "is_closing", client_session, binance_client)

            # signal_exit_result = self.signal_exit_control.check_signal_exit(
            #     close_signal=close_signal,
            #     cur_nPnl=cur_nPnl,
            #     normalized_sign=normalized_sign,
            #     settings_pos_options=settings_pos_options,
            #     debug_label=debug_label
            # )

            # if signal_exit_result:              
            #     return compose_signals(user_name, strategy_name, symbol, position_side, "is_closing", client_session, binance_client)

            avg_result = self.avg_control.check_avg_and_report(
                cur_price=cur_price,
                symbol_data=symbol_position_data,
                nPnL_calc=self.pos_utils.nPnL_calc,
                normalized_sign=normalized_sign,
                avg_signal=avg_signal,
                settings_pos_options=settings_pos_options,
                debug_label=debug_label
            )
            
            if avg_result:
                return compose_signals(user_name, strategy_name, symbol, position_side, "is_avg", client_session, binance_client)

        except aiohttp.ClientError as e:
            self.error_handler.debug_error_notes(f"[HTTP Error] Failed to monitor position for {debug_label}: {e}", True)
        except Exception as e:
            self.error_handler.debug_error_notes(f"[Unexpected Error] Failed to monitor position for {debug_label}: {e}", True)