# from a_settings import TokensTemplate
from b_context import BotContext
from c_log import ErrorHandler, log_time
from d_bapi import BinancePublicApi
import asyncio 
import aiohttp
from random import uniform
import pandas as pd
from pprint import pprint

MAX_CONCURRENT_REQUESTS = 5
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

class CoinFilter:
    def __init__(
            self,
            context: BotContext, 
            error_handler: ErrorHandler, 
            binance_public :BinancePublicApi
        ):
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context
        self.binance_public = binance_public

    @staticmethod
    def get_settings(sourse_setting):
        tfr:      str =   sourse_setting["tfr"]
        period:   int =   sourse_setting["period"]
        min_rule: float = sourse_setting["range"][0]
        max_rule: float = sourse_setting["range"][1]

        return tfr, period, min_rule, max_rule

    @staticmethod
    def mean_calc(df, column_name):
        return df[column_name].dropna().mean()
        
    @staticmethod
    def delta_fn(df, column_name):
        df = df[(df['High'] != df['Low']) & (df['Low'] != 0)].copy()
        df[column_name] = ((df['High'] - df['Low']) / df['Low']) * 100
        return df[column_name].mean()

    async def metric_filter(
        self,
        session: aiohttp.ClientSession,
        user: str,
        sourse_setting: dict,
        symbol: str,
        column_name: str,
        metric_calc_fn: callable
    ):
        try:
            tfr, period, min_rule, max_rule = self.get_settings(sourse_setting)
            df = await self.binance_public.get_klines_basic(
                session=session,
                symbol=symbol,
                interval=tfr,
                limit=period
            )

            if df is None or df.empty:
                return None

            # Подсчёт метрики
            value = metric_calc_fn(df, column_name)
            if value is None or pd.isna(value):
                return None
            # pprint(f"[{user}][{symbol}][{tfr}][{column_name}]: {value:.4f}")

            min_ok = (min_rule is None) or (value >= min_rule)
            max_ok = (max_rule is None) or (value < max_rule)

            return (min_ok and max_ok), round(value, 2)

        except Exception as ex:
            self.error_handler.debug_error_notes(f"[ERROR][metric_filter][{user}][{symbol}][{column_name}]: {ex}")
            return None

    async def filter_symbol(self, session, user, symbol, filter_set):
        async with semaphore:
            await asyncio.sleep(uniform(0.25, 0.46))

            async def apply_metric(filter_config, column_name, metric_fn):
                if not filter_config["enable"]:
                    return False, None
                result = await self.metric_filter(
                    session=session,
                    user=user,
                    sourse_setting=filter_config,
                    symbol=symbol,
                    column_name=column_name,
                    metric_calc_fn=metric_fn
                )
                return result if result else (False, None)

            volume_ok, mean_UsdtVolum = await apply_metric(
                filter_set["volum"], "QuoteVolume", self.mean_calc
            )

            delta_ok1, mean_delta1 = await apply_metric(
                filter_set["delta1"], "DeltaPct1", self.delta_fn,
            )

            delta_ok2, mean_delta2 = await apply_metric(
                filter_set["delta2"], "DeltaPct2", self.delta_fn,
            )

            return {
                "symbol": symbol,
                "mean_UsdtVolum": mean_UsdtVolum if volume_ok else None,
                "mean_delta1": mean_delta1 if delta_ok1 else None,
                "mean_delta2": mean_delta2 if delta_ok2 else None,
            }
        
    async def sweet_filter(self, session, user, symbols, filter_set):
        tasks = [self.filter_symbol(session, user, symbol, filter_set) for symbol in symbols]
        results = await asyncio.gather(*tasks)

        # Сбор отфильтрованных
        return {
            r["symbol"]: {
                "mean_UsdtVolum": r["mean_UsdtVolum"],
                "mean_delta1": r["mean_delta1"],
                "mean_delta2": r["mean_delta2"],
            }
            for r in results if r
        }

    async def apply_filter_settings(self, session, user, symbols):
        filter_set = self.context.total_settings[user]["filter"]
        if not filter_set["enable"]:
            return

        filtered_symbols = await self.sweet_filter(session, user, symbols, filter_set)

        if not filtered_symbols:
            return

        for symbol, filter_details in filtered_symbols.items():
            # pprint({
            #     "symbol": symbol,
            #     **filter_details
            # })

            user_data = self.context.dinamik_risk_data.setdefault(user, {})
            symbol_data = user_data.setdefault(symbol, {})
            for risk_suffics in ["sl", "tp"]:                
                risk_rate = filter_set[f"{risk_suffics}_risk_rate"]
                if not risk_rate:
                    continue

                symbol_data[risk_suffics] = (
                    filter_details.get("mean_delta2") * risk_rate
                    if filter_details.get("mean_delta2") is not None
                    else None
                )

    def print_report(self):
        print(f"📋 Cron Filter Report, {log_time()}:\n")
        for user, symbols in self.context.dinamik_risk_data.items():
            print(f"👤 User: {user}")
            for symbol, risk_data in symbols.items():
                print(f"   🔹 Symbol: {symbol}")
                for suffix, value in risk_data.items():
                    print(f"      ▪ {suffix.upper()}: {value}")
            print("-" * 40)