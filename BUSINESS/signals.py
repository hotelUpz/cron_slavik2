import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import pandas as pd
import pandas_ta as ta
import re
import numpy as np
from typing import *
from numba import njit
from c_initializer import BotContext
from c_log import ErrorHandler
from c_validators import TimeframeValidator, validate_dataframe
import traceback


def extract_signal_func_name(strategy_name: str) -> str:
    # Удаляет всё после первого подчеркивания или цифр, если есть, оставляя только префикс
    match = re.match(r"^([a-zA-Z]_+)", strategy_name)
    return match.group(1).lower() if match else strategy_name.lower()

@njit
def filter_signals(signals):
    result = np.zeros_like(signals)
    prev = 0
    for i in range(len(signals)):
        sig = signals[i]
        if sig != 0 and sig != prev:
            result[i] = sig
            prev = sig
    return result

def aggregate_candles(df: pd.DataFrame, timeframe: str = "5m") -> pd.DataFrame:
    if timeframe == "1m": return df
    df_resampled = df.resample(timeframe.replace('m', 'min')).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()
    return df_resampled

class INDICATORS:
    def __init__(
            self,
            context: BotContext, 
            error_handler: ErrorHandler
        ):
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context

    def trend_ema_calc(self, df, ind_rules):
        empty_signals = pd.Series([0] * len(df), index=df.index, name="TREND_EMA", dtype=int)
        try:
            enable = ind_rules['enable']
            if not enable:
                # self.error_handler.debug_info_notes("[DEBUG][TREND_EMA] Индикатор отключён. Возврат нулевой серии.")
                return empty_signals

            period1 = ind_rules['period1']
            period2 = ind_rules['period2']
            col_name = ind_rules['col_name']
            is_trend: int = int(ind_rules.get("is_trend", 1))

            if len(df) < min(period1, period2):
                # self.error_handler.debug_info_notes(
                #     f"[DEBUG][TREND_EMA] Недостаточно данных: длина df={len(df)} меньше min(period1, period2)={min(period1, period2)}. Возврат нулевой серии."
                # )
                return empty_signals

            if period2 == 1 or period1 >= period2:
                self.stop_bot = True
                self.error_handler.debug_info_notes(
                    "[ERROR][TREND_EMA] Некорректные параметры: period1 не может быть больше или равен period2.", important=True
                )
                raise ValueError("period1 не может быть больше или равен period2")

            # Если период == 1, используем оригинальные значения
            ema1 = df[col_name] if period1 == 1 else ta.ema(df[col_name], length=period1)
            ema2 = ta.ema(df[col_name], length=period2)

            signals = np.select(
                condlist=[ema1 > ema2, ema1 < ema2],
                choicelist=[1 * is_trend, -1 * is_trend],
                default=0
            )

            return pd.Series(signals, index=df.index, name="TREND_EMA", dtype=int)

        except Exception as ex:
            self.error_handler.debug_info_notes(f"[ERROR][TREND_EMA] Исключение: {ex}", important=True)
            return empty_signals    
                
    def stochrsi_calc(self, df, ind_rules):
        empty_signals = pd.Series([0] * len(df), index=df.index, name="STOCHRSI", dtype=int)
        try:
            enable = ind_rules['enable']
            if not enable:
                # self.error_handler.debug_info_notes("[DEBUG][STOCHRSI] Индикатор отключён. Возврат нулевой серии.")
                return empty_signals
            
            period = ind_rules.get('period', 14)
            k = ind_rules.get('k', 3)
            d = ind_rules.get('d', 3)
            over_buy = ind_rules.get('over_buy', 70)
            over_sell = ind_rules.get('over_sell', 30)

            if len(df) < period + k + d:
                # self.error_handler.debug_info_notes(
                #     f"[DEBUG][STOCHRSI] Недостаточно данных: длина df={len(df)} меньше period+k+d={period + k + d}. Возврат нулевой серии."
                # )
                return empty_signals

            stochrsi_df = ta.stochrsi(df['Close'], length=period, k=k, d=d)
            k_series = stochrsi_df.iloc[:, 0]
            d_series = stochrsi_df.iloc[:, 1]

            signals_val = np.select(
                condlist=[
                    (k_series <= over_sell) & (d_series <= over_sell),
                    (k_series >= over_buy) & (d_series >= over_buy)
                ],
                choicelist=[1, -1],
                default=0
            )

            return pd.Series(signals_val, index=df.index, name="STOCHRSI", dtype=int)

        except Exception as ex:
            self.error_handler.debug_info_notes(f"[ERROR][STOCHRSI] Исключение: {ex}", important=True)
            return empty_signals

    def volf_calc(self, df: pd.DataFrame, ind_rules: dict) -> pd.Series:
        """
        """        
        try:
            signals = pd.Series(False, index=df.index, name="VOLF", dtype=bool)
            enable = ind_rules['enable']
            if not enable:
                # вернуть все сигналы истинными
                return signals
            
            if 'Volume' not in df.columns:
                self.error_handler.debug_error_notes("volf_calc: отсутствует колонка 'Volume'")
                return signals

            period = ind_rules.get('period')
            if not isinstance(period, int) or period <= 0:
                self.error_handler.debug_error_notes(f"volf_calc: некорректный period = {period}")
                return signals

            if len(df) < period + 1:
                self.error_handler.debug_error_notes("volf_calc: недостаточно данных для расчёта.")
                return signals

            mode = ind_rules.get('mode', 'a')
            if mode not in ('r', 'a'):
                self.error_handler.debug_error_notes(f"volf_calc: неизвестный режим '{mode}'")
                return signals

            slice_factor = ind_rules.get(mode, {}).get('slice_factor', 1.0)
            volume = df['Volume'].abs()
            last_vol = volume.iloc[-1]

            # Берём предыдущие period баров (исключая последний)
            ref_values = volume.iloc[-(period + 1):-1]

            if mode == 'a':
                past_max = ref_values.max()
                # print(f"past_max: {past_max}")
                if pd.notna(past_max) and last_vol > past_max * slice_factor:
                    signals.iloc[-1] = True

            elif mode == 'r':
                past_avg = ref_values.mean()
                # print(f"past_avg: {past_avg}")
                if pd.notna(past_avg) and last_vol > past_avg * slice_factor:
                    signals.iloc[-1] = True

            return signals

        except Exception as ex:
            self.error_handler.debug_error_notes(f"volf_calc ошибка: {ex}")
            return signals 

    # def ema_cross_calc(self, df, params):
    #     """
    #     Боевой EMA-кроссовер с фильтром ускорения и импульса.
    #     Возвращает Series: 1 — покупка, -1 — продажа, 0 — нет сигнала.
    #     """
    #     try:
    #         period1 = params['period1']
    #         period2 = params['period2']

    #         if len(df) < max(period1, period2) + 5:
    #             return pd.Series(np.nan, index=df.index, name='EMA_CROSS')

    #         ema1 = ta.ema(df['Close'], length=period1)
    #         ema2 = ta.ema(df['Close'], length=period2)
    #         ema_diff = ema1 - ema2

    #         # Импульс: усиливающееся расхождение (просто сравнение изменений)
    #         delta_now = abs(ema_diff - ema_diff.shift(1))
    #         delta_prev = abs(ema_diff.shift(1) - ema_diff.shift(2))
    #         impulse = delta_now > delta_prev

    #         # Кроссы с учётом импульса
    #         cross_up = (
    #             (ema_diff > 0) &
    #             (ema_diff.shift(2) < 0) &
    #             (ema_diff.shift(1) > ema_diff.shift(2)) &
    #             impulse
    #         )

    #         cross_down = (
    #             (ema_diff < 0) &
    #             (ema_diff.shift(2) > 0) &
    #             (ema_diff.shift(1) < ema_diff.shift(2)) &
    #             impulse
    #         )

    #         signals = pd.Series(0, index=df.index, dtype=np.int8)
    #         signals[cross_up] = 1
    #         signals[cross_down] = -1

    #         return signals.rename('EMA_CROSS')

    #     except Exception as ex:
    #         print(f"ema_cross_calc: {ex}")
    #         return pd.Series(dtype=int, index=df.index, name='EMA_CROSS')
        
    # # ///////
    # def hvh_calc(self, df, ind_rules):
    #     """
    #     HVH-индикатор с режимами:
    #     - "fixed": фиксированная макс. девиация за окно
    #     - "rolling": скользящее макс. отклонение

    #     ind_rules:
    #         - "period": окно MA и девиации
    #         - "dev": множитель девиации
    #         - "mode": "fixed" или "rolling"
    #         - "is_trend": 1 или 0
    #     """
    #     try:
    #         ma_period = int(ind_rules.get("period", 0))
    #         deviation_rate = float(ind_rules.get("dev", 1.0))
    #         is_trend = int(ind_rules.get("is_trend", 1))
    #         mode = ind_rules.get("mode", "rolling").lower()

    #         if ma_period <= 0:
    #             raise ValueError("hvh_calc: параметр 'period' должен быть положительным.")

    #         if len(df) < ma_period:
    #             return pd.Series(dtype=int, index=df.index, name="HVH")

    #         close = df["Close"]
    #         high = df["High"]
    #         low = df["Low"]

    #         ma = close.rolling(window=ma_period, min_periods=ma_period).mean()
    #         high_dev = np.where(high > ma, (high - ma).abs(), 0)
    #         low_dev = np.where(low < ma, (ma - low).abs(), 0)
    #         deviation = pd.Series(np.maximum(high_dev, low_dev), index=df.index)

    #         if mode == "fixed":
    #             valid_dev = deviation[-ma_period:].dropna()
    #             if valid_dev.empty:
    #                 raise ValueError("hvh_calc: недостаточно валидных данных для fixed-девиации.")
                
    #             max_dev = valid_dev.max()
    #             adj_dev_value = max_dev * deviation_rate
    #             adj_dev = pd.Series(adj_dev_value, index=df.index)

    #         elif mode == "rolling":
    #             rolling_max_dev = deviation.rolling(window=ma_period, min_periods=ma_period).max()
    #             adj_dev_series = rolling_max_dev * deviation_rate
    #             adj_dev = pd.Series(adj_dev_series, index=df.index)

    #         else:
    #             raise ValueError("hvh_calc: неизвестный режим. Используйте 'fixed' или 'rolling'.")

    #         direction = np.where(close >= ma, 1, -1)
    #         trigger = ma + (adj_dev * direction)

    #         raw_signals = np.zeros(len(close), dtype=np.int8)
    #         raw_signals[(close >= trigger) & (direction == 1)] = 1 * is_trend
    #         raw_signals[(close <= trigger) & (direction == -1)] = -1 * is_trend
    #         filtered = filter_signals(raw_signals)

    #         return pd.Series(filtered, index=df.index, name="HVH")

    #     except Exception as ex:
    #         print(f"hvh_calc: {ex}")
    #         return pd.Series(dtype=int, index=df.index, name="HVH")
        
    # def adx_calc(self, df, ind_rules):
    #     """Возвращает ADX как Series"""
    #     period = ind_rules['period']
        
    #     if len(df) < period:
    #         return pd.Series(dtype=float, index=df.index, name="ADX")
        
    #     adx_resp = ta.adx(df['High'], df['Low'], df['Close'], length=period)
    #     adx = adx_resp[f'ADX_{period}']
    #     if isinstance(adx, pd.DataFrame):
    #         adx = adx.iloc[:, 0]
    #     return pd.Series(adx.values, index=df.index, name="ADX")
    
    # def rsi_calc(self, df, ind_rules):
    #     """Возвращает RSI как Series"""       
    #     period = ind_rules['period']

    #     if len(df) < period:
    #         return pd.Series(dtype=float, index=df.index, name="RSI")
        
    #     rsi = ta.rsi(df['Close'], length=period)            
    #     if isinstance(rsi, pd.DataFrame):
    #         rsi = rsi.iloc[:, 0]
    #     return pd.Series(rsi.values, index=df.index, name="RSI")  
    # 
    # 

    def cron_ind_calc(self, df, ind_rules):
        return pd.Series([True] * len(df), index=df.index, name="CRON_IND", dtype=bool)

class SIGNALS(INDICATORS):
    def __init__(
            self,
            context: BotContext, 
            error_handler: ErrorHandler, 
            tfr_valid: TimeframeValidator,
        ):
        super().__init__(context, error_handler)
        error_handler.wrap_foreign_methods(self)   
        self.tfr_valid = tfr_valid    
        self.default_columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']

    def signals_debug(self, msg, symbol=None):
        self.error_handler.debug_info_notes(f"{msg} (Symbol: {symbol})" if symbol else msg, True)

    def extract_df(self, symbol, time_frame):
        default_df = pd.DataFrame(columns=self.default_columns)
        try:
            klines_lim = self.context.ukik_suffics_data.get("klines_lim")
            suffics = f"_{klines_lim}_{time_frame}"        
            return self.context.klines_data_cache.get(f"{symbol}{suffics}", default_df)
        except:
            return default_df
    
    def compose_signals(
            self, user_name, strategy_name, symbol,
            position_side, status, client_session, binance_client):
        debug_label = f"[{user_name}][{strategy_name}][{symbol}][{position_side}]"
        symbol_data = self.context.position_vars[user_name][strategy_name][symbol]
        return {
            "status": status,
            "user_name": user_name,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "position_side": position_side,
            "pos_side": position_side,
            "position_data": symbol_data[position_side],
            "qty_precision": symbol_data.get("qty_precision"),
            "debug_label": debug_label,  
            "client_session": client_session,
            "binance_client": binance_client,                  
        }

    def volf_stoch_colab(self, data, symbol, is_close_bar, ind_suffics, entry_rules):
        """Генерация сигналов Trend + Volume Filter с учетом закрытия бара."""

        def is_valid_volf_data(data, required_cols):
            return all(col in data.columns and pd.notna(data[col].iloc[-1]) for col in required_cols)

        # Проверка закрытия свечи
        if is_close_bar:
            compatible, is_closed = self.tfr_valid.tfr_validate(entry_rules)
            if not compatible or not is_closed:
                if not compatible:
                    self.error_handler.debug_error_notes(f"[volf][{symbol}]: таймфреймы не совместимы.")
                return 0, 0
        else:
            is_closed = True

        # Названия колонок индикаторов
        trend_ema_column = f"TREND_EMA_{ind_suffics}"
        volf_column = f"VOLF_{ind_suffics}"
        stoch_rsi_column = f"STOCHRSI_{ind_suffics}"

        # Получаем параметры включения индикаторов из настроек
        trend_enabled = entry_rules.get('TREND_EMA', {}).get('enable', True)
        stoch_rsi_enabled = entry_rules.get('STOCHRSI', {}).get('enable', True)
        volf_enabled = entry_rules.get('VOLF', {}).get('enable', True)

        # Формируем список колонок для проверки только по включённым индикаторам
        required_cols = ["Volume"]  # Volume всегда проверяем
        if trend_enabled:
            required_cols.append(trend_ema_column)
        if stoch_rsi_enabled:
            required_cols.append(stoch_rsi_column)
        if volf_enabled:
            required_cols.append(volf_column)

        # Проверка наличия данных и ненулевых значений последних баров
        if not is_valid_volf_data(data, required_cols):
            missing_cols = [col for col in required_cols
                            if col not in data.columns or pd.isna(data[col].iloc[-1])]
            self.error_handler.debug_error_notes(f"[volf][{symbol}]: недостаточно данных. NaN в: {missing_cols}")
            return 0, 0

        # Получаем последние значения индикаторов (только включенные)
        trend_ema_val = data[trend_ema_column].iloc[-1] if trend_enabled else None
        volf_val = data[volf_column].iloc[-1] if volf_enabled else None
        stoch_rsi_val = data[stoch_rsi_column].iloc[-1] if stoch_rsi_enabled else None

        # Логика тренда
        if trend_enabled:
            long_trend_ok = trend_ema_val == 1
            short_trend_ok = trend_ema_val == -1
        else:
            long_trend_ok = True
            short_trend_ok = True

        # Логика стохастик RSI
        if stoch_rsi_enabled:
            stochrsi_long_ok = stoch_rsi_val == 1
            stochrsi_short_ok = stoch_rsi_val == -1
        else:
            stochrsi_long_ok = True
            stochrsi_short_ok = True

        # Логика volf
        if volf_enabled:
            volf_ok: bool = bool(volf_val)
        else:
            volf_ok = True

        # Итоговая генерация сигналов
        long_open = long_trend_ok and stochrsi_long_ok and volf_ok and is_closed
        short_open = short_trend_ok and stochrsi_short_ok and volf_ok and is_closed

        long_signal = 1 if long_open else 2 if short_open else 0
        short_signal = -1 if short_open else -2 if long_open else 0

        return long_signal, short_signal
    
    def cron_colab(self, data, symbol, is_close_bar, ind_suffics, entry_rules):
        """Генерация сигналов. """

        # Проверка закрытия свечи
        if is_close_bar:
            compatible, is_closed = self.tfr_valid.tfr_validate(entry_rules)
            if not compatible or not is_closed:
                if not compatible:
                    self.error_handler.debug_error_notes(f"[volf][{symbol}]: таймфреймы не совместимы.")
                # print("not is_closed")
                return 0, 0
            
        # print(f"is_closed: {is_closed}")
        return 1, -1

    # def ema_cross_colab(self, data, symbol, is_close_bar, ind_suffics, entry_rules):
    #     """Генерация сигналов EMA Cross с учетом закрытия свечи."""

    #     def is_valid_ema_cross_data(data, ema_cross_col):
    #         required_cols = [ema_cross_col, "Close"]
    #         return all(col in data.columns and pd.notna(data[col].iloc[-1]) for col in required_cols)

    #     ema_cross_column = f"EMA_CROSS_{ind_suffics}"

    #     # Проверка закрытия свечи, если требуется
    #     if is_close_bar:
    #         compatible, is_closed = self.tfr_valid.tfr_validate(entry_rules)
    #         if not compatible or not is_closed:
    #             if not compatible:
    #                 self.debug_info_notes(f"[ema_cross][{symbol}] ❌ Несовместимые таймфреймы в entry_rules.")
    #             return 0, 0
    #     else:
    #         is_closed = True

    #     # Проверка наличия и валидности данных
    #     if not is_valid_ema_cross_data(data, ema_cross_column):
    #         missing_or_nan = [col for col in [ema_cross_column, "Close"]
    #                         if col not in data.columns or pd.isna(data[col].iloc[-1])]
    #         self.debug_info_notes(f"[ema_cross][{symbol}] ❌ Недостаточно данных. Проблемы с колонками: {missing_or_nan}")
    #         return 0, 0

    #     ema_val = data[ema_cross_column].iloc[-1]

    #     open_long = ema_val == 1 and is_closed
    #     open_short = ema_val == -1 and is_closed

    #     long_signal = 1 if open_long else 2 if open_short else 0
    #     short_signal = -1 if open_short else -2 if open_long else 0

#         # self.debug_info_notes(
#         #     f"[ema_cross][{symbol}] ✅ Проверка пройдена | "
#         #     f"EMA_CROSS: {ema_val}, is_closed: {is_closed} → "
#         #     f"long_signal: {long_signal}, short_signal: {short_signal}"
#         # )

    #     return long_signal, short_signal
    
    # def hvh_trend_colab(self, data, symbol, is_close_bar, ind_suffics, entry_rules):
    #     """Генерация сигналов HVH Trend с учетом закрытия свечи."""

    #     def is_valid_hvh_data(data, hvh_col, adx_col):
    #         required_cols = [hvh_col, adx_col, "Close"]
    #         return all(col in data.columns and pd.notna(data[col].iloc[-1]) for col in required_cols)

    #     if is_close_bar:
    #         compatible, is_closed = self.tfr_validate(entry_rules)
    #         if not compatible or not is_closed:
    #             if not compatible:
    #                 self.debug_error_notes(f"[hvh_trend][{symbol}]: таймфреймы не совместимы")
    #             return 0, 0
    #     else:
    #         is_closed = True

    #     hvh_column = f"HVH_{ind_suffics}"
    #     adx_column = f"ADX_{ind_suffics}"
    #     adx_threshold = entry_rules.get('ADX', {}).get('threshold', 20)

    #     if not is_valid_hvh_data(data, hvh_column, adx_column):
    #         missing = [col for col in [hvh_column, adx_column, "Close"] if col not in data.columns or pd.isna(data[col].iloc[-1])]
    #         self.debug_error_notes(f"[hvh_trend][{symbol}] ❌ Невалидные данные, отсутствуют или NaN: {missing}")
    #         return 0, 0

    #     hvh_val = data[hvh_column].iloc[-1]
    #     adx_val = data[adx_column].iloc[-1]
    #     adx_ok = adx_val > adx_threshold

    #     open_long = (hvh_val == 1) and adx_ok and is_closed
    #     open_short = (hvh_val == -1) and adx_ok and is_closed

    #     long_signal = 1 if open_long else 2 if open_short else 0
    #     short_signal = -1 if open_short else -2 if open_long else 0

#         # self.debug_info_notes(
#         #     f"[hvh_trend][{symbol}] HVH={hvh_val}, ADX={adx_val:.2f} (threshold={adx_threshold}), is_closed={is_closed} | "
#         #     f"long_signal={long_signal}, short_signal={short_signal}"
#         # )


    #     return long_signal, short_signal

    # def hvh_contr_colab(self, data, symbol, is_close_bar, ind_suffics, entry_rules):
    #     """Генерация сигналов HVH Contrarian с учетом закрытия свечи."""

    #     def is_valid_hvh_data(data, hvh_col, rsi_col):
    #         required_cols = [hvh_col, rsi_col, "Close"]
    #         return all(col in data.columns and pd.notna(data[col].iloc[-1]) for col in required_cols)

    #     if is_close_bar:
    #         compatible, is_closed = self.tfr_validate(entry_rules)
    #         if not compatible or not is_closed:
    #             if not compatible:
    #                 self.debug_error_notes(f"[hvh_contr][{symbol}]: таймфреймы не совместимы")
    #             return 0, 0
    #     else:
    #         is_closed = True

    #     hvh_column = f"HVH_{ind_suffics}"
    #     rsi_column = f"RSI_{ind_suffics}"
    #     rsi_over_buy = entry_rules.get('RSI', {}).get('over_buy', 70)
    #     rsi_over_sell = entry_rules.get('RSI', {}).get('over_sell', 30)

    #     if not is_valid_hvh_data(data, hvh_column, rsi_column):
    #         missing = [col for col in [hvh_column, rsi_column, "Close"] if col not in data.columns or pd.isna(data[col].iloc[-1])]
    #         self.debug_error_notes(f"[hvh_contr][{symbol}] ❌ Невалидные данные, отсутствуют или NaN: {missing}")
    #         return 0, 0

    #     hvh_val = data[hvh_column].iloc[-1]
    #     rsi_val = data[rsi_column].iloc[-1]

    #     open_long = (hvh_val == 1) and (rsi_val <= rsi_over_sell) and is_closed
    #     open_short = (hvh_val == -1) and (rsi_val >= rsi_over_buy) and is_closed

    #     long_signal = 1 if open_long else 2 if open_short else 0
    #     short_signal = -1 if open_short else -2 if open_long else 0

#         # self.debug_info_notes(
#         #     f"[hvh_contr][{symbol}] HVH={hvh_val}, RSI={rsi_val:.2f} (OverBuy={rsi_over_buy}, OverSell={rsi_over_sell}), is_closed={is_closed} | "
#         #     f"long_signal={long_signal}, short_signal={short_signal}"
#         # )

    #     return long_signal, short_signal
    
    # ////
    def signal_interpreter(
        self,
        long_signal: int,
        short_signal: int,
        in_position: bool,
        position_side: str,
        config_direction: List,
        reverse: bool,
        any_in_position: bool,
        long_count: int,
        short_count: int,
        long_limit: int = float("inf"),
        short_limit: int = float("inf")
    ) -> tuple[bool, bool]:
        
        is_long = position_side == "LONG"
        is_short = position_side == "SHORT"

        open_signal = not in_position and (
            (long_signal == 1 and is_long) or 
            (short_signal == -1 and is_short)
        ) and (
            (not reverse and position_side in config_direction) or
            (reverse and not any_in_position)
        )

        if open_signal:
            if is_long and long_count >= long_limit:
                open_signal = False
            elif is_short and short_count >= short_limit:
                open_signal = False

        avg_signal = in_position and (
            (long_signal == 1 and is_long) or 
            (short_signal == -1 and is_short)
        )

        close_signal = in_position and (
            (long_signal == 2 and is_long) or 
            (short_signal == -2 and is_short)
        )

        return open_signal, avg_signal, close_signal
    
    def get_signal(
            self,  
            user_name: str,
            strategy_name: str,          
            symbol: str,
            position_side: str,
            config_direction: List[str],
            ind_suffics: str,
            long_count: dict,
            short_count: dict
        ):

        open_signal, avg_signal, close_signal = False, False, False
        force_martin = False

        try:
            # --- Сокращения ---
            user_settings = self.context.total_settings[user_name]["core"]
            strategy_settings = self.context.strategy_notes[strategy_name][position_side]
            entry_conditions = strategy_settings.get("entry_conditions", {})
            signal_on = entry_conditions.get("grid_orders")[0].get("signal")

            symbol_vars = self.context.position_vars[user_name][strategy_name][symbol]

            symbol_pos_data = symbol_vars[position_side]
            in_position = symbol_pos_data.get("in_position", False)

            any_in_position = any(
                side_data.get("in_position", False)
                for side_data in (symbol_vars.get("LONG", {}), symbol_vars.get("SHORT", {}))
            )

            # --- MARTIN GALE LOGIC ---
            symbols_risk = self.context.total_settings[user_name]["symbols_risk"]
            symbol_key = symbol if symbol in symbols_risk else "ANY_COINS"
            sbl_risk = symbols_risk[symbol_key]
            reverse_side = reverse = False

            if sbl_risk.get("is_martin") and not in_position:          
                pos_martin = (
                    self.context.position_vars
                        .setdefault(user_name, {})
                        .setdefault(strategy_name, {})
                        .setdefault(symbol, {})
                        .setdefault("martin", {})
                        .setdefault(position_side, {})
                )

                force_martin = sbl_risk.get("force_martin")
                reverse = sbl_risk.get("reverse")

                if pos_martin.get("success") == -1:
                    reverse_side = reverse                    
                    if force_martin:
                        open_signal, avg_signal, close_signal = True, False, False                        
                        return  # результат вернём через finally

            # --- Настройки сигналов ---
            gen_signal_func_name = extract_signal_func_name(strategy_name)
            # print(gen_signal_func_name)
            entry_rules = entry_conditions.get("rules", {})
            is_close_bar = entry_conditions.get("is_close_bar", False)

            # --- Данные по минимальному ТФ ---
            min_tfr = self.context.ukik_suffics_data["min_tfr"]
            origin_df = self.extract_df(symbol, min_tfr)

            if not signal_on:
                open_signal = True
                return  # результат вернём через finally

            # --- Кэш индикаторов по ТФ ---
            tfr_cache = {}
            for ind_marker, ind_rules in entry_rules.items():
                ind_name = (ind_rules.get("ind_name") or "").strip().lower()
                if not ind_name:
                    continue

                calc_ind_func = getattr(self, f"{ind_name}_calc", None)
                if not callable(calc_ind_func):
                    self.signals_debug(f"❌ Indicator function not found: {ind_name}", symbol)
                    continue

                tfr = ind_rules.get("tfr")
                if tfr not in tfr_cache:
                    tfr_cache[tfr] = self.extract_df(symbol, tfr)
                process_df = tfr_cache[tfr]

                new_ind_column = calc_ind_func(process_df, ind_rules)
                if isinstance(new_ind_column, pd.Series):
                    unik_column_name = f"{ind_marker.strip()}_{ind_suffics}"
                    origin_df[unik_column_name] = new_ind_column.reindex(origin_df.index).ffill()
                else:
                    self.signals_debug(
                        f"❌ Invalid indicator output (not Series). Symbol: {symbol}",
                        symbol
                    )

            del tfr_cache

            # --- Вычисляем сигнал ---
            signal_func = getattr(self, gen_signal_func_name + "_colab", None)
            # if callable(signal_func) and validate_dataframe(origin_df):
            if callable(signal_func):
                result = signal_func(origin_df, symbol, is_close_bar, ind_suffics, entry_rules)
                if isinstance(result, (tuple, list)) and len(result) == 2:
                    long_signal, short_signal = result
                    open_signal, avg_signal, close_signal = self.signal_interpreter(
                        long_signal,
                        short_signal,
                        in_position,
                        position_side,
                        config_direction,
                        reverse,
                        any_in_position,
                        long_count[user_name],
                        short_count[user_name],
                        user_settings.get("long_positions_limit", float("inf")),
                        user_settings.get("short_positions_limit", float("inf")),
                    )
            else:
                self.signals_debug("❌ Signal function not found or invalid dataframe", symbol)

        except Exception as e:
            tb = traceback.format_exc()
            self.signals_debug(
                f"❌ Signal function error for [{user_name}][{strategy_name}][{symbol}][{position_side}]: {e}\n{tb}",
                symbol
            )
        finally:
            if open_signal:
                if position_side == "LONG":
                    long_count[user_name] += 1
                elif position_side == "SHORT":
                    short_count[user_name] += 1

            return open_signal, avg_signal, close_signal, reverse_side
