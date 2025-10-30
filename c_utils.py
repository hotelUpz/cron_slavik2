from typing import Dict, List, Optional, Set, Tuple
import re
from datetime import datetime, timezone
from b_context import BotContext
from c_log import ErrorHandler, log_time, TIME_ZONE
from decimal import Decimal, getcontext


getcontext().prec = 28  # точность Decimal

PRECISION = 28

def format_duration(ms: int) -> str:
    """
    Конвертирует миллисекундную разницу в формат "Xh Ym" или "Xm" или "Xs".
    :param ms: длительность в миллисекундах
    """
    if ms is None:
        return ""
    
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0 and seconds > 0:
        return f"{minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return f"{seconds}s"

def milliseconds_to_datetime(milliseconds):
    if milliseconds is None:
        return "N/A"
    try:
        ms = int(milliseconds)   # <-- приведение к int
        if milliseconds < 0: return "N/A"
    except (ValueError, TypeError):
        return "N/A"

    if ms > 1e10:  # похоже на миллисекунды
        seconds = ms / 1000
    else:
        seconds = ms

    dt = datetime.fromtimestamp(seconds, TIME_ZONE)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def to_human_digit(value):
    if value is None:
        return "N/A"
    getcontext().prec = PRECISION
    dec_value = Decimal(str(value)).normalize()
    if dec_value == dec_value.to_integral():
        return format(dec_value, 'f')
    else:
        return format(dec_value, 'f').rstrip('0').rstrip('.') 

def format_msg(
    cfg: dict,
    indent: int = 0,
    target_key: str = None,
    alt_key: str = None,
    ex_key: str = None,
) -> str:
    lines = []
    pad = "  " * indent

    for k, v in cfg.items():
        # исключаем ключ
        if k == ex_key:
            continue

        # заменяем имя ключа
        display_key = alt_key if k == target_key else k

        if isinstance(v, dict):
            lines.append(f"{pad}• {display_key}:")
            lines.append(format_msg(v, indent + 1, target_key, alt_key, ex_key))
        else:
            lines.append(f"{pad}• {display_key}: {v}")

    return "\n".join(lines)


class PositionUtils:
    """Утилиты для работы с позициями и торговыми направлениями."""

    def __init__(self, context: BotContext, error_handler: ErrorHandler):    
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context

    @staticmethod
    def extract_all_periods(rule):
        """Извлекает все значения period, period1, period2 и т.д. из одного правила."""
        periods = []
        for key, v in rule.items():
            if re.fullmatch(r"period\d*", key, re.IGNORECASE) or key.lower() == "period":
                try:
                    period = int(v)
                    periods.append(period)
                except (ValueError, TypeError):
                    continue
        return periods

    @staticmethod
    def get_avi_directions(direction_mode: int, dubug_label: str) -> Optional[List[str]]:
        """
        Возвращает доступные направления торговли на основе direction_mode.
        """
        directions = {
            1: ["LONG"],
            2: ["SHORT"],
            3: ["LONG", "SHORT"]
        }
        result = directions.get(direction_mode)
        if result is None:
            print(f"{dubug_label}. Параметр direction задан неверно")
        return result

    @staticmethod
    def count_active_symbols(position_vars: Dict) -> Tuple[int, int, Set[str]]:
        """
        Подсчитывает активные символы и количество LONG/SHORT позиций.
        """
        if not isinstance(position_vars, dict):
            raise TypeError("position_vars must be a dictionary")

        active_symbols: Set[str] = set()
        long_count = {}
        short_count = {}

        for user_name, strategies in position_vars.items():
            long_count[user_name] = 0
            short_count[user_name] = 0
            if not isinstance(strategies, dict):
                continue

            for strategy_data in strategies.values():  # volf_stoch → {...}
                for symbol, symbol_data in strategy_data.items():  # BRUSDT → {...}
                    symbol_active = False
                    for pos_type, pos_data in symbol_data.items():  # LONG / SHORT
                        if not isinstance(pos_data, dict):
                            continue
                        if pos_data.get("in_position", False):
                            symbol_active = True
                            if pos_type == "LONG":
                                long_count[user_name] += 1
                            elif pos_type == "SHORT":
                                short_count[user_name] += 1
                    if symbol_active:
                        active_symbols.add(symbol)

        return long_count, short_count, active_symbols
    
    def has_any_failed_position(self) -> bool:
        """Есть ли хотя бы одна позиция с success == -1"""
        for user_name, strategies in self.context.position_vars.items():
            for strategy_name, symbols in strategies.items():
                for symbol, symbol_data in symbols.items():
                    martin_data = symbol_data.get("martin", {})
                    for position_side in ("LONG", "SHORT"):
                        pos_martin = martin_data.get(position_side, {})
                        if pos_martin.get("success") == -1:
                            return True
        return False
    
    @staticmethod
    def get_qty_precisions(symbol_info, symbol):
        symbol_data = next((item for item in symbol_info["symbols"] if item['symbol'] == symbol), None)
        if not symbol_data:
            return

        lot_size_filter = next((f for f in symbol_data["filters"] if f["filterType"] == "LOT_SIZE"), None)
        price_filter = next((f for f in symbol_data["filters"] if f["filterType"] == "PRICE_FILTER"), None)

        if not lot_size_filter or not price_filter:
            return

        def count_decimal_places(number_str):
            if '.' in number_str:
                return len(number_str.rstrip('0').split('.')[-1])
            return 0

        qty_precission = count_decimal_places(lot_size_filter['stepSize'])
        price_precision = count_decimal_places(price_filter['tickSize'])

        return qty_precission, price_precision

    def size_calc(
        self,
        margin_size: float,
        entry_price: float,
        leverage: float,
        volume_rate: float,
        precision: int,
        dubug_label: str
    ) -> Optional[float]:
        """
        Рассчитывает количество (quantity) для сделки.
        """
        if any(not isinstance(x, (int, float)) or x <= 0 for x in [margin_size, entry_price, leverage]):
            self.error_handler.debug_error_notes(f"{dubug_label}: Invalid input parameters in size_calc")
            return None

        try:
            deal_amount = margin_size * volume_rate
            raw_qty = (deal_amount * leverage) / entry_price
            qty = round(raw_qty, precision)

            # # === DEBUGGING METRICS (можно закомментировать при необходимости) ===
            # self.error_handler.debug_error_notes(f"{dubug_label}: margin_size = {margin_size}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: volume_rate = {volume_rate}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: deal_amount = margin_size * volume_rate = {deal_amount}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: leverage = {leverage}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: entry_price = {entry_price}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: raw_qty = (deal_amount * leverage) / entry_price = {raw_qty}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: precision = {precision}")
            # self.error_handler.debug_error_notes(f"{dubug_label}: final qty = {qty}")
            # # ====================================================================

            return qty
        except Exception as e:
            self.error_handler.debug_error_notes(f"{dubug_label}: Error in size_calc: {e}")
            return None

        
    def nPnL_calc(
            self,
            cur_price: float,
            init_price: float,
            dubug_label: str,
        ) -> float:
        """Расчет процентного изменения цены с защитой от None и нуля"""
        dubug_label = dubug_label + "[nPnL]"

        if not isinstance(cur_price, (int, float)) or cur_price <= 0.0:
            self.error_handler.debug_error_notes(f"{dubug_label} Некорректный cur_price: {cur_price}")
            return None

        if not isinstance(init_price, (int, float)) or init_price <= 0.0:
            self.error_handler.debug_error_notes(f"{dubug_label} Некорректный init_price: {init_price}")
            return None

        return (cur_price - init_price) / init_price * 100
    

class TimingUtils:
    """Управляет таймингом. """

    def __init__(self, error_handler: ErrorHandler, inspection_interval: str = "1m"):    
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.interval_seconds: int = self.interval_to_seconds(inspection_interval)
        self.last_fetch_timestamp = None   
    
    @staticmethod
    def interval_to_seconds(interval):
        """
        Преобразует строковый интервал Binance в количество секунд.
        """
        mapping = {
            "1m": 60,
            "2m": 120,
            "3m": 180,
            "4m": 240,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "12h": 43200,
            "1d": 86400,
        }
        return mapping.get(interval, 60)  # По умолчанию "1m"

    def time_scheduler(self):
        """
        Проверяет, появилась ли новая метка времени кратная интервалу.
        """
        
        now = datetime.now(timezone.utc)  # Используем объект времени с временной зоной UTC
        current_timestamp = int(now.timestamp())

        # Рассчитываем ближайшую кратную метку времени
        nearest_timestamp = (current_timestamp // self.interval_seconds) * self.interval_seconds

        if self.last_fetch_timestamp is None or nearest_timestamp > self.last_fetch_timestamp:
            self.last_fetch_timestamp = nearest_timestamp
            return True

        return False