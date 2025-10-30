import asyncio
import aiofiles
import pandas as pd
from random import choice
from pathlib import Path
from collections import OrderedDict
import pickle
from typing import *
from b_context import BotContext
from c_log import ErrorHandler
from c_validators import validate_dataframe
# import traceback
import os

BASE_DIR = Path(__file__).resolve().parents[1]  # до корня проекта

DEBUG_DIR = BASE_DIR / "INFO" / "DEBUG"
TRADES_DIR = BASE_DIR / "INFO" / "TRADES"

DEBUG_ERR_FILE = DEBUG_DIR / "error_.txt"
DEBUG_INFO_FILE = DEBUG_DIR / "info_.txt"
TRADES_INFO_FILE = TRADES_DIR / "info_.txt"
TRADES_SECONDARY_FILE = TRADES_DIR / "secondary_.txt"
TRADES_FAILED_FILE = TRADES_DIR / "failed_.txt"
TRADES_SUCC_FILE = TRADES_DIR / "success_.txt"



class KlinesCacheManager:
    def __init__(self, context: BotContext, error_handler: ErrorHandler, get_klines: Callable):    
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context
        self.get_klines = get_klines
        self.klines_lim = self.context.ukik_suffics_data.get("klines_lim")
        # print(self.klines_lim)
        self.avi_tfr = self.context.ukik_suffics_data.get("avi_tfr")
        self.fetch_symbols = self.context.fetch_symbols
        self.api_key_list = [x.get("proxy_url", None) for _, x in self.context.total_settings.items()]
        # print(f"api_key_list: {self.api_key_list}")
        self.default_columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']

    def get_klines_scheduler(self, active_symbols, interval_completed):
        return (
            (interval_completed and not self.context.first_iter) or 
            (self.context.first_iter and active_symbols)
        )

    async def update_klines(self, new_klines, symbol: str, suffics: str):
        full_symbol = f"{symbol}{suffics}"
        if full_symbol not in self.context.klines_data_cache:
            self.context.klines_data_cache[full_symbol] = pd.DataFrame(columns=self.default_columns)

        if validate_dataframe(new_klines):
            self.context.klines_data_cache[full_symbol] = new_klines
        else:
            self.error_handler.debug_error_notes(f"[update_klines] Невалидные данные для {full_symbol}.")

    async def fetch_klines_for_symbols(
        self, session, symbols: set, interval: str, fetch_limit: int, api_key_list: list = None
    ):
        """
        Асинхронно получает свечи для списка символов по заданному таймфрейму.
        """
        MAX_CONCURRENT_REQUESTS = 20
        REQUEST_DELAY = 0.1
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def fetch_kline(symbol):
            async with semaphore:
                try:
                    await asyncio.sleep(REQUEST_DELAY)
                    api_key = choice(api_key_list) if api_key_list else None
                    return symbol, await self.get_klines(session, symbol, interval, fetch_limit, api_key)
                except Exception as e:
                    self.error_handler.debug_error_notes(f"Ошибка при получении свечей для {symbol} [{interval}]: {e}")
                    return symbol, pd.DataFrame(columns=self.default_columns)

        tasks = [fetch_kline(symbol) for symbol in symbols]
        return await asyncio.gather(*tasks)

    async def process_timeframe(self, session, time_frame: str, fetch_symbols: set, fetch_limit: int, api_key_list: list):
        """
        Обработка одного таймфрейма для всех символов.
        """
        suffics = f"_{fetch_limit}_{time_frame}"
        klines_result = await self.fetch_klines_for_symbols(session, fetch_symbols, time_frame, fetch_limit, api_key_list)
        for symbol, new_klines in klines_result:
            await self.update_klines(new_klines, symbol, suffics)

    async def total_klines_handler(self, session):
        """
        Получение и обновление свечей для всех символов и всех доступных таймфреймов.
        """
        try:
            tasks = [
                self.process_timeframe(session, time_frame, self.fetch_symbols, self.klines_lim, self.api_key_list)
                for time_frame in self.avi_tfr
            ]
            await asyncio.gather(*tasks)

        except Exception as e:
            self.error_handler.debug_error_notes(f"[ERROR] in total_klines_handler: {e}")
            return
        
# ///        
class FileManager:
    def __init__(self, error_handler: ErrorHandler):   
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler

    async def cache_exists(self, file_name="pos_cache.pkl"):
        """Проверяет, существует ли файл и не пустой ли он."""
        return await asyncio.to_thread(lambda: os.path.isfile(file_name) and os.path.getsize(file_name) > 0)

    async def load_cache(self, file_name="pos_cache.pkl"):
        """Читает данные из pickle-файла."""
        def _load():
            with open(file_name, "rb") as file:
                return pickle.load(file)
        try:
            return await asyncio.to_thread(_load)
        except (FileNotFoundError, EOFError):
            return {}
        except Exception as e:
            self.error_handler.debug_error_notes(f"Unexpected error while reading {file_name}: {e}")
            return {}        

    def _write_pickle(self, data, file_name):
        with open(file_name, "wb") as file:
            pickle.dump(data, file, protocol=pickle.HIGHEST_PROTOCOL)

    async def write_cache(self, data_dict, file_name="pos_cache.pkl"):
        """Сохраняет данные в pickle-файл."""
        try:
            await asyncio.to_thread(self._write_pickle, data_dict, file_name)
        except Exception as e:
            self.error_handler.debug_error_notes(f"Error while caching data: {e}")


class WriteLogManager(FileManager):
    """Управляет асинхронной записью логов в файлы и очисткой списков логов."""

    def __init__(self, error_handler: ErrorHandler, max_log_lines: int = 250) -> None:
        super().__init__(error_handler)
        self.MAX_LOG_LINES: int = max_log_lines

    async def write_logs(self) -> None:
        logs: List[Tuple[List[str], Path]] = [
            (self.error_handler.debug_err_list, DEBUG_ERR_FILE),
            (self.error_handler.debug_info_list, DEBUG_INFO_FILE),
            (self.error_handler.trade_info_list, TRADES_INFO_FILE),
            (self.error_handler.trade_failed_list, TRADES_FAILED_FILE),
            (self.error_handler.trade_succ_list, TRADES_SUCC_FILE),
        ]

        for log_list, file_path in logs:
            if not log_list:
                continue

            file_path.parent.mkdir(parents=True, exist_ok=True)  # Создаёт директорию, если не существует

            existing_lines: List[str] = []
            if file_path.exists():
                async with aiofiles.open(str(file_path), "r", encoding="utf-8") as f:
                    existing_lines = await f.readlines()

            new_lines = [f"{log}\n" for log in log_list]
            total_lines = existing_lines + new_lines
            total_lines = list(OrderedDict.fromkeys(total_lines))

            if len(total_lines) > self.MAX_LOG_LINES:
                total_lines = total_lines[-self.MAX_LOG_LINES:]

            async with aiofiles.open(str(file_path), "w", encoding="utf-8") as f:
                await f.writelines(total_lines)

            log_list.clear()

        self.error_handler.trade_secondary_list.clear()

        