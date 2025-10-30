import asyncio
from typing import  Dict, Set
from a_settings import FILTER_WINDOW

class BotContext:
    def __init__(self):
        """ Инициализируем глобальные структуры"""

        # Переменные состояния бота
        self.first_iter: bool = True
        self.stop_bot: bool = False

        # Статическая информация
        self.symbol_info: dict = {}
        self.fetch_symbols: Set[str] = set()
        # self.klines_lim: int = 0
        self.cron_cycle_interval: str = "1m"
        self.cron_filter_interval: str = FILTER_WINDOW

        # Настройки и текущие данные
        self.strategy_notes: dict = {}
        self.total_settings: dict = {}  
        self.user_contexts: dict = {}
        self.api_key_list: list = []

        # Переменные позиции
        self.first_update_done: dict[str, bool] = {}
        self.position_vars: dict = {}
        self.dinamik_risk_data: dict = {}
        self.ws_price_data: Dict[str, Dict[str, float]] = {}    
        self.anti_double_close: dict = {}
        self.klines_data_cache: dict = {}
        self.ukik_suffics_data: dict = {}
        self.report_list = []

        # Ссылки на глобальные объекты
        self.async_lock: asyncio.Lock = asyncio.Lock()
        self.ws_async_lock: asyncio.Lock = asyncio.Lock()