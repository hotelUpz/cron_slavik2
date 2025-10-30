from copy import deepcopy
from a_settings import *
from a_strategies import StrategySettings
from b_context import BotContext
from c_log import ErrorHandler
from c_utils import PositionUtils
from c_validators import validate_symbol
# from pprint import pprint


DEFAULT_STRATEGY_TEMPLATE = {
    "LONG": {
        "entry_conditions": {"rules": {}},
        "exit_conditions": {"rules": {}},
    },
    "SHORT": {
        "entry_conditions": {"rules": {}},
        "exit_conditions": {"rules": {}},
    },
}


class BaseDataInitializer:
    def __init__(
            self,
            context: BotContext, 
            error_handler: ErrorHandler, 
            pos_utils: PositionUtils
        ):
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context
        self.pos_utils = pos_utils

    def init_base_structure(self):
        users_data: dict = deepcopy(UsersSettings().users_config)

        # Отфильтруем сразу активные стратегии у всех пользователей
        active_strategy_names: set = set()
        for user_data in users_data.values():
            for strategy_name, strategy_cfg in user_data.get("strategies_symbols", []):
                if strategy_cfg.get("is_active"):
                    active_strategy_names.add(strategy_name)

        # Отфильтруем strategy_notes — оставим только активные
        all_strategy_notes: list = [
            (name, cfg) for name, cfg in StrategySettings().strategy_notes
            if name in active_strategy_names
        ]

        # print(all_strategy_notes)

        self._load_user_data(users_data)
        if self.context.stop_bot:
            return

        self._validate_strategy_notes(all_strategy_notes)
        if self.context.stop_bot:
            return

        self._compute_historical_limits(all_strategy_notes)
        self._get_strategy_notes(all_strategy_notes)

        ## DEBUG:
        # pprint(context.total_settings)
        # print(context.fetch_symbols)
        # print(context.klines_lim)
        # pprint(context.strategy_notes)

    def _get_strategy_notes(self, all_strategy_notes: list):
        self.context.strategy_notes = dict(all_strategy_notes)

    # def _get_strategy_notes(self, all_strategy_notes: list):
    #     notes = {}
    #     for name, cfg in all_strategy_notes:
    #         # Базовый каркас
    #         base_cfg = deepcopy(DEFAULT_STRATEGY_TEMPLATE)

    #         # Обновляем данными из cfg
    #         for side in ("LONG", "SHORT"):
    #             if side in cfg:
    #                 for section, section_cfg in cfg[side].items():
    #                     if section in base_cfg[side] and isinstance(section_cfg, dict):
    #                         base_cfg[side][section].update(section_cfg)
    #                     else:
    #                         base_cfg[side][section] = section_cfg

    #         notes[name] = base_cfg

    #     self.context.strategy_notes = notes

    def _has_duplicate_keys(self, pair_list: list, source_name: str, user: str = "") -> bool:
        keys_only = [k[0] for k in pair_list]
        duplicates = set(k for k in keys_only if keys_only.count(k) > 1)
        if duplicates:
            prefix = f"У пользователя '{user}' " if user else ""
            print(f"❌ {prefix}обнаружены дубликаты в '{source_name}': {duplicates}")
            self.context.stop_bot = True
            return True
        return False

    def _compute_historical_limits(self, all_strategy_notes):
        tfr_map = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "6h": 360,
            "12h": 720, "1d": 1440, "1w": 10080
        }

        required_minutes_list = []
        avi_tfr = set()

        for direct in ("LONG", "SHORT"):
            for strategy_name, strategy_details in all_strategy_notes:
                if strategy_name not in self._avi_strategies:
                    continue

                rules = (
                    strategy_details.get(direct, {})
                    .get("entry_conditions", {})
                    .get("rules", {})
                )

                for rule in rules.values():
                    # Игнорируем неактивные индикаторы
                    if not rule.get("enable", False):
                        continue
                    tfr_str = rule.get("tfr")
                    if tfr_str:
                        avi_tfr.add(tfr_str)

                    # tfr_in_min = tfr_map.get(tfr_str, 1) if tfr_str else 1
                    periods = self.pos_utils.extract_all_periods(rule)

                    for period in periods:
                        required_minutes_list.append(period)

        klines_lim = max(required_minutes_list) * 5 if required_minutes_list else 0
        min_tfr_key = min(avi_tfr, key=lambda tfr: tfr_map.get(tfr, float("inf"))) if avi_tfr else None

        # финальная структура
        self.context.ukik_suffics_data = {
            "avi_tfr": list(avi_tfr),
            "min_tfr": min_tfr_key,
            "klines_lim": klines_lim,
        }

    def _validate_strategy_notes(self, all_strategy_notes):
        strategy_keys = [k[0] for k in all_strategy_notes if k]
        if self._has_duplicate_keys(all_strategy_notes, source_name="StrategySettings().strategy_notes"):
            raise

        for user_data in self.context.total_settings.values():
            for strategy_name in user_data.get("strategies_symbols", {}).keys():
                if strategy_name not in strategy_keys:
                    print(f"❌ Неизвестная стратегия '{strategy_name}' не найдена в StrategySettings().strategy_notes")
                    self.context.stop_bot = True
                    raise

        self._avi_strategies = strategy_keys  # сохранить для `_compute_historical_limits`

    def _load_user_data(self, users_data):
        for user, user_data in users_data.items():
            raw_config = user_data.get("strategies_symbols", [])
            raw_config = [k for k in raw_config if k and k[1].get("is_active")]

            if self._has_duplicate_keys(raw_config, source_name="strategies_symbols", user=user):
                return

            quote_asset = user_data.get("core", {}).get("quote_asset", "USDT").strip() or "USDT"
            user_defined_risk = deepcopy(user_data.get("symbols_risk", {}))
            strategies_symbols, user_symbol_risk = {}, {}

            for strategy_name, strat_cfg in raw_config:
                dubug_label = f"[{user}][{strategy_name}]"
                raw_symbols = strat_cfg.get("symbols", set())
                symbols_with_suffix = set()

                for symbol in raw_symbols:
                    if not symbol or not symbol.strip():
                        continue
                    base = symbol.strip()
                    if not validate_symbol(base):
                        self.error_handler.debug_error_notes(f"⚠️ {dubug_label}: символ {symbol} пуст либо поврежден. ")
                        raise
                    full_symbol = base + quote_asset
                    symbols_with_suffix.add(full_symbol)

                    if base in user_defined_risk:
                        user_symbol_risk[full_symbol] = user_defined_risk[base]

                strat_cfg["symbols"] = symbols_with_suffix
                self.context.fetch_symbols.update(symbols_with_suffix)
                strategies_symbols[strategy_name] = strat_cfg
                del strategies_symbols[strategy_name]["is_active"]

            if not strategies_symbols:
                print(f"⚠️ У пользователя '{user}' нет активных стратегий — пропускаем.")
                continue

            if "ANY_COINS" in user_defined_risk:
                user_symbol_risk["ANY_COINS"] = user_defined_risk["ANY_COINS"]

            # 🛠️ Прокси формирование
            proxy_cfg = user_data.get("proxy", {})
            proxy_url = None
            if proxy_cfg.get("is_active"):
                try:
                    login = proxy_cfg.get("proxy_login")
                    password = proxy_cfg.get("proxy_password")
                    host = proxy_cfg.get("proxy_address")
                    port = proxy_cfg.get("proxy_port")
                    proxy_url = f"http://{login}:{password}@{host}:{port}"
                    self.context.api_key_list.append(proxy_url)
                except Exception as e:
                    print(f"⚠️ Ошибка формирования прокси URL для '{user}': {e}")

            # user_symbol_risk = {
            #     s: {**v, "cur_margin_size": v.get("margin_size", 0.0)}
            #     for s, v in user_symbol_risk.items()
            # }

            core = user_data.get("core", {}).copy()
            if "direction" in core:
                core["direction"] = self.pos_utils.get_avi_directions(
                    core["direction"],
                    user
                )

            self.context.total_settings[user] = {
                "keys": user_data.get("keys", {}),
                "core": core,
                "strategies_symbols": strategies_symbols,
                "symbols_risk": user_symbol_risk,
                "filter": user_data.get("filter", {}),
                "proxy_url": proxy_url,  # ← добавили сюда
            }

        if not self.context.total_settings:
            print("❌ Нет подходящих пользователей с активными стратегиями.")
            self.context.stop_bot = True

class PositionVarsSetup:
    def __init__(
            self,
            context: BotContext, 
            error_handler: ErrorHandler, 
            pos_utils: PositionUtils
        ):
        error_handler.wrap_foreign_methods(self)
        self.error_handler = error_handler
        self.context = context
        self.pos_utils = pos_utils
    
    @staticmethod
    def pos_vars_root_template():
        """Базовый шаблон переменных позиции"""
        return {
            "trailing_sl_progress_counter": 0,
            "avg_progress_counter": 1,
            "avg_price": None,
            "entry_price": None,
            "comul_qty": None,
            "notional": None,
            "in_position": False,
            "problem_closed": False,
            "sl_order_id": None,
            "tp_order_id": None,            
            # "symbols_prison": set(),
            "offset": 0.0,
            "activation_percent": 0.0,
            "process_volume": 0.0,
            "is_tp": False,
            "is_sl": False,
            "c_time": None
        }
            
    def set_pos_defaults(self, symbol_data, symbol, pos_type):
        """Безопасная инициализация структуры данных контроля позиций."""
        qty_prec, price_prec = None, None
        try:
            precisions = self.pos_utils.get_qty_precisions(self.context.symbol_info, symbol)
            if isinstance(precisions, (list, tuple)) and len(precisions) >= 2:
                qty_prec, price_prec = precisions[0], precisions[1]
            else:
                self.error_handler.debug_error_notes(f"⚠️ [INFO]: Не удается получить precisions для {symbol}")
        except Exception as e:
            self.error_handler.debug_error_notes(f"⚠️ [ERROR] при получении precisions для {symbol}: {e}")
            self.context.stop_bot = True
            raise RuntimeError(f"Ошибка получения precision для {symbol}: {e}")

        if qty_prec is None or price_prec is None:
            # self.context.stop_bot = True
            # raise RuntimeError(f"❌ Не удалось определить qty/price precision для {symbol}")
            print(f"❌ Не удалось определить qty/price precision для {symbol}")
            return False

        # Устанавливаем значения, если они еще не заданы
        symbol_data.setdefault("qty_precision", qty_prec)
        symbol_data.setdefault("price_precision", price_prec)
        symbol_data.setdefault("martin", {
            "LONG": {
                "success": 1,
                "cur_margin_size": None,
            },
            "SHORT": {
                "success": 1,
                "cur_margin_size": None,
            },
        })

        # Убедимся, что pos_type существует в данных символа
        symbol_data.setdefault(pos_type, {}).update(self.pos_vars_root_template())
        return True

    def setup_pos_vars(self):
        """Инициализация структуры данных контроля позиций"""
        bad_symbols = set()
        for user_name, details in self.context.total_settings.items():
            dubug_label = f"[{user_name}]"

            if user_name not in self.context.position_vars:
                self.context.position_vars[user_name] = {}

            for strategy_name, strategy_details in details.get("strategies_symbols").items():
                if strategy_name not in self.context.position_vars:
                    self.context.position_vars[user_name][strategy_name] = {}
                
                symbols = strategy_details.get("symbols", set())
                if not symbols:
                    self.error_handler.debug_error_notes(f"⚠️ {dubug_label}: символы пусты. ")
                    raise

                for pos_type in ["LONG", "SHORT"]:
                    for symbol in symbols.copy():
                        symbol_data = self.context.position_vars[user_name][strategy_name].setdefault(symbol, {})
                        if not self.set_pos_defaults(symbol_data, symbol, pos_type):
                            bad_symbols.add(symbol)
                            break

        self.context.fetch_symbols -= bad_symbols
