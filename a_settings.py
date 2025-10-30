class TokensTemplate():
    tokens_template = {
        'AAVE', 'ADA', 'ALGO', 'APT', 'ARB', 'ATOM', 'AVAX',
        'BAT', 'BCH', 'BNB', 'BR',
        'CHZ', 'CROSS',
        'DASH', 'DOGE', 'DOT',
        'ENJ', 'ETC', 'ETH',
        'FIL',
        'GALA',
        'ICX',
        'IOTA',
        'JASMY',
        'KAS', 'KNC',
        'LINK', 'LTC',
        'MANA', 'MKR',
        'NEO',
        'ONT',
        'OP',
        'PYTH',
        'QTUM',
        'SOL', 'SUI',
        'TAO', 'TIA', 'TRX',
        'UNI', 
        'VET',
        'WIF',
        'XLM', 'XMR', 'XRP', 'XTZ',
        'ZEC', 'ZIL'
    }


class UsersSettings():
    users_config = {
        "Slavik": {                                  # -- имя пользователя
            "keys": {
                "BINANCE_API_PUBLIC_KEY": "yUCSKOy5R9mI7m1g0FBoLbjuAYQdhuzivtACOdIYZZ2cr1NqRnynXJ6EqL6cKi3f", # Славик base
                "BINANCE_API_PRIVATE_KEY": "LGtTD2UfJwbir1HOjNwB23UHsTqgW8IoPuc2yR3XjYGoCiBWqREJSgY4o5RWEOTJ"
            },

            # "proxy": {
            #     "is_active": True,
            #     "proxy_address": '154.218.20.43',
            #     "proxy_port": '64630',
            #     "proxy_login":'1FDJcwJR',
            #     "proxy_password": 'U2yrFg4a'
            # },
            # "proxy": {
            #     "is_active": True,
            #     "proxy_address": '93.157.104.3',
            #     "proxy_port": '64514',
            #     "proxy_login":'1FDJcwJR',
            #     "proxy_password": 'U2yrFg4a'
            # },
            "proxy": {
                "is_active": True,
                "proxy_address": '45.192.135.214',
                "proxy_port": '59100',
                "proxy_login":'nikolassmsttt0Icgm',
                "proxy_password": 'agrYpvDz7D'
            },
            # 1FDJcwJR:U2yrFg4a@154.222.214.132:62890
            

            "core": { 
                "margin_type": "CROSSED",         # Тип маржи. Кросс-маржа → "CROSSED", Изолированная → "ISOLATED"
                "quote_asset": "USDT",            # → валюта, в которой указана цена (например, USDT, USDC, BUSD)
                "direction": 3,                   # 1 -- LONG, 2 --SHORT, 3 -- BOTH
                "long_positions_limit": 7,        # количество одновременно открываемых лонгов
                "short_positions_limit": 7,       # количество одновременно открываемых шортов
            },

            "symbols_risk": {
                "TAC": {
                    "margin_size": 33.2,          # размер маржи в USDT (либо другой базовой валюте)
                    "leverage": 10,               # размер плеча. Общий объем на сделку == (margin_size x leverage)
                    "sl": None,                   # %, float, отрицательное значение. Отключено -- None
                    "fallback_sl": None,          # tp на случай отказа основного тейка
                    "tp": 0.6,  # TP              # %, float, положительное значение. Отключено -- None
                    "tp_order_type": "LIMIT",     # MARKET | LIMIT
                    "fallback_tp": 0.9,           # tp на случай отказа основного тейка
                    "is_martin": False,           # использовать Мартин Гейл
                    "force_martin": False,        # Перезаходим по Мартину, не дожидаясь нового сигнала
                    "martin_multipliter": 2.5,    # множитель Мартин Гейла
                    "reverse": False              # reverse при Мартине
                },
                "UB": {
                    "margin_size": 33.2,          # размер маржи в USDT (либо другой базовой валюте)
                    "leverage": 10,               # размер плеча. Общий объем на сделку == (margin_size x leverage)
                    "sl": None,                   # %, float, отрицательное значение. Отключено -- None
                    "fallback_sl": None,          # tp на случай отказа основного тейка
                    "tp": 0.6,  # TP              # %, float, положительное значение. Отключено -- None
                    "tp_order_type": "LIMIT",     # MARKET | LIMIT
                    "fallback_tp": 0.9,           # tp на случай отказа основного тейка
                    "is_martin": False,           # использовать Мартин Гейл
                    "force_martin": False,        # Перезаходим по Мартину, не дожидаясь нового сигнала
                    "martin_multipliter": 2.5,    # множитель Мартин Гейла
                    "reverse": False              # reverse при Мартине
                },

                "ANY_COINS": {
                    "margin_size": 47.5,          # размер маржи в USDT (либо другой базовой валюте)
                    "leverage": 10,               # размер плеча. Общий объем на сделку == (margin_size x leverage)
                    "sl": None,                   # %, float, отрицательное значение. Отключено -- None
                    "fallback_sl": None,          # tp на случай отказа основного тейка
                    "tp": 0.6,  # TP              # %, float, положительное значение. Отключено -- None
                    "tp_order_type": "LIMIT",     # MARKET | LIMIT
                    "fallback_tp": 0.9,           # tp на случай отказа основного тейка
                    "is_martin": False,           # использовать Мартин Гейл
                    "force_martin": False,        # Перезаходим по Мартину, не дожидаясь нового сигнала
                    "martin_multipliter": 2.5,    # множитель Мартин Гейла
                    "reverse": False              # reverse при Мартине
                },
            },

            "filter": {                   # настройки фильтра
                "enable": False,
                "tp_risk_rate": 0.99,     # корректор найденного динамического take-profit (+ float)
                "sl_risk_rate": 0.99,     # корректор найденного динамического stop-loss (+ float)
                "volum": {
                    "enable": False,
                    "tfr": "1d",
                    "range": (3_000_000, None),  
                    "period": 5,                 # Период для расчета

                },
                "delta1": {
                    "enable": False,
                    "tfr": "1d",
                    "range": (5, 60),          # % ценовая дельта
                    "period": 5,               # Период для расчета
                },
                "delta2": {
                    "enable": False,
                    "tfr": "5m",
                    "range": (0.6, None),       # % ценовая дельта
                    "period": 24,               # Период для расчета
                },

            },

            "strategies_symbols": [
                # ("volf_stoch", {                                  # -- название стратегии
                #     "is_active": True,
                #     "symbols": TokensTemplate().tokens_template,  # -- список токенов (выбрать из шаблона)
                #     # "symbols": {"MYX", "MANA", "XTZ", "DASH"},         # -- -//- (либо указать вручную)
                # }),
                ("cron", {                                  # -- название стратегии
                    "is_active": True,
                    # "symbols": TokensTemplate().tokens_template,  # -- список токенов (выбрать из шаблона)
                    "symbols": {"UB", "BR", "ARIA", "PLAY", "REI", "SOPH", "TAC"},         # -- -//- (либо указать вручную)
                }),
            ],
        },

        # "Nik": {                                  # -- имя пользователя
        #     "keys": {
        #         "BINANCE_API_PUBLIC_KEY": "Vz2ImnNehZn8fCpsnUn7cUcaBCZ5TuS5RW4CqCUZH2pxcv9KUzCvXOgxJygXw1yc", # -- my base
        #         "BINANCE_API_PRIVATE_KEY": "h0uGoxCeDF9U2mk0NJvWvKld0rTsoV0pWFyCgqoH78NFRIicAXYf6KHkh6GCIitB",
        #     },

        #     # "keys": {
        #     #     "BINANCE_API_PUBLIC_KEY": "atvd6xJm8aCJKyCeeqnFdidbNoHAz4OwHMBVEMNCnfhKjUoiJ2F6LPJ11eHeyoZ5", # Ira base
        #     #     "BINANCE_API_PRIVATE_KEY": "0QOqV5mlLLPFUIIVxc7kSIjAqKVFEWrKje1d2sT0UkCrsXc7DD4wYNgn39wCTvyG"
        #     # },

        #     "proxy": {
        #         "is_active": False,
        #         "proxy_address": '154.218.20.43',
        #         "proxy_port": '64630',
        #         "proxy_login":'1FDJcwJR',
        #         "proxy_password": 'U2yrFg4a'
        #     },

        #     "core": { 
        #         "margin_type": "CROSSED",         # Тип маржи. Кросс-маржа → "CROSSED", Изолированная → "ISOLATED"
        #         "quote_asset": "USDT",            # → валюта, в которой указана цена (например, USDT, USDC, BUSD)
        #         "direction": 3,                   # 1 -- LONG, 2 --SHORT, 3 -- BOTH
        #         "long_positions_limit": 4,        # количество одновременно открываемых лонгов
        #         "short_positions_limit": 4,       # количество одновременно открываемых шортов
        #     },

        #     "symbols_risk": {
        #         # # ____________________ # -- здесь через запятую точечная настройка рисков для конкретного символа (как ниже)
        #         # "UB": {
        #         #     "margin_size": 42.0,          # размер маржи в USDT (либо другой базовой валюте)
        #         #     "leverage": 20,              # размер плеча. Общий объем на сделку == (margin_size x leverage)
        #         #     "sl": None,                  # %, float, отрицательное значение. Отключено -- None
        #         #     "tp": 0.6,  # TP             # %, float, положительное значение. Отключено -- None
        #         #     "tp_order_type": "LIMIT",    # MARKET | LIMIT
        #         #     "is_martin": False,           # использовать Мартин Гейл
        #         #     "force_martin": True,        # Перезаходим по Мартину, не дожидаясь нового сигнала
        #         #     "martin_multipliter": 2.5,   # множитель Мартин Гейла
        #         #     "reverse": False              # reverse при Мартине
        #         # },
        #         # # ____________________ # -- здесь через запятую точечная настройка рисков для конкретного символа (как ниже)
        #         # "TAC": {
        #         #     "margin_size": 42.0,         # размер маржи в USDT (либо другой базовой валюте)
        #         #     "leverage": 20,              # размер плеча. Общий объем на сделку == (margin_size x leverage)
        #         #     "sl": None,                  # %, float, отрицательное значение. Отключено -- None
        #         #     "tp": 0.6,  # TP             # %, float, положительное значение. Отключено -- None
        #         #     "tp_order_type": "LIMIT",    # MARKET | LIMIT
        #         #     "is_martin": False,           # использовать Мартин Гейл
        #         #     "force_martin": True,        # Перезаходим по Мартину, не дожидаясь нового сигнала
        #         #     "martin_multipliter": 2.5,   # множитель Мартин Гейла
        #         #     "reverse": False              # reverse при Мартине
        #         # },
        #         # "BR": {
        #         #     "margin_size": 5.25,          # размер маржи в USDT (либо другой базовой валюте)
        #         #     "leverage": 20,              # размер плеча. Общий объем на сделку == (margin_size x leverage)
        #         #     "sl": None,                  # %, float, отрицательное значение. Отключено -- None
        #         #     "tp": 0.7,  # TP             # %, float, положительное значение. Отключено -- None
        #         #     "tp_order_type": "LIMIT",    # MARKET | LIMIT
        #         #     "is_martin": False,           # использовать Мартин Гейл
        #         #     "force_martin": True,        # Перезаходим по Мартину, не дожидаясь нового сигнала
        #         #     "martin_multipliter": 2.5,   # множитель Мартин Гейла
        #         #     "reverse": False              # reverse при Мартине
        #         # },
        #         # # ____________________ # -- здесь через запятую точечная настройка рисков для конкретного символа (как ниже)
        #         # "ARIA": {
        #         #     "margin_size": 5.25,         # размер маржи в USDT (либо другой базовой валюте)
        #         #     "leverage": 20,              # размер плеча. Общий объем на сделку == (margin_size x leverage)
        #         #     "sl": None,                  # %, float, отрицательное значение. Отключено -- None
        #         #     "tp": 0.75,  # TP             # %, float, положительное значение. Отключено -- None
        #         #     "tp_order_type": "LIMIT",    # MARKET | LIMIT
        #         #     "is_martin": False,           # использовать Мартин Гейл
        #         #     "force_martin": True,        # Перезаходим по Мартину, не дожидаясь нового сигнала
        #         #     "martin_multipliter": 2.5,   # множитель Мартин Гейла
        #         #     "reverse": False              # reverse при Мартине
        #         # },
        #         "ANY_COINS": {
        #             "margin_size": 21.0,          # размер маржи в USDT (либо другой базовой валюте)
        #             "leverage": 16,              # размер плеча. Общий объем на сделку == (margin_size x leverage)
        #             "sl": None,                  # %, float, отрицательное значение. Отключено -- None
        #             "fallback_sl": None,           # tp на случай отказа основного тейка
        #             "tp": 0.6,  # TP             # %, float, положительное значение. Отключено -- None
        #             "tp_order_type": "LIMIT",    # MARKET | LIMIT
        #             "fallback_tp": 0.9,           # tp на случай отказа основного тейка
        #             "is_martin": False,           # использовать Мартин Гейл
        #             "force_martin": False,        # Перезаходим по Мартину, не дожидаясь нового сигнала
        #             "martin_multipliter": 2.5,   # множитель Мартин Гейла
        #             "reverse": False              # reverse при Мартине
        #         },
        #     },

        #     "filter": {                   # настройки фильтра
        #         "enable": False,
        #         "tp_risk_rate": 0.99,     # корректор найденного динамического take-profit (+ float)
        #         "sl_risk_rate": 0.99,     # корректор найденного динамического stop-loss (+ float)
        #         "volum": {
        #             "enable": False,
        #             "tfr": "1d",
        #             "range": (3_000_000, None),  
        #             "period": 5,                 # Период для расчета

        #         },
        #         "delta1": {
        #             "enable": False,
        #             "tfr": "1d",
        #             "range": (5, 60),          # % ценовая дельта
        #             "period": 5,               # Период для расчета
        #         },
        #         "delta2": {
        #             "enable": False,
        #             "tfr": "5m",
        #             "range": (0.6, None),       # % ценовая дельта
        #             "period": 24,               # Период для расчета
        #         },

        #     },

        #     "strategies_symbols": [
        #         # ("volf_stoch", {                                  # -- название стратегии
        #         #     "is_active": True,
        #         #     "symbols": TokensTemplate().tokens_template,  # -- список токенов (выбрать из шаблона)
        #         #     # "symbols": {"MYX", "MANA", "XTZ", "DASH"},         # -- -//- (либо указать вручную)
        #         # }),
        #         ("cron", {                                  # -- название стратегии
        #             "is_active": True,
        #             # "symbols": TokensTemplate().tokens_template,  # -- список токенов (выбрать из шаблона)
        #             "symbols": {"UB", "BR", "ARIA", "PLAY"},         # -- -//- (либо указать вручную)
        #             # "symbols": {"TAC"},         # -- -//- (либо указать вручную)
        #         }),
        #     ],
        # },
    }

TG_BOT_TOKEN: str = "8315504290:AAFbXDKxtK3nxRTTzn6G2vsPx9nevp9yzcg" # -- токен бота
TG_BOT_ID: str = "610822492" # -- id бота

FILTER_WINDOW: str = "5m" # (1m, 2m, 3m, 4m, 5m, 15m, 30m, 1h, 2h, 4h, 12h, 1d)

# ----------- UTILS ---------------
WAIT_CLOSE_CANDLE: int = 5                 # sec. Ожидаем формирования новой свечи
TZ_STR: str = "Europe/Kyiv"                # часовой пояс ("Europe/Berlin")
MAX_LOG_LINES: int = 1001                  # количество строк в лог файлах

# --------- SYSTEM ----------------
USE_CACHE: bool = False                    # использовать кеш для восстановления позиции. При деплое на сервер можно отключить 
POS_UPDATE_FREQUENCY: float = 1.2         # seconds. частота обновления позиций при контроле состояния позиций
MAIN_CYCLE_FREQUENCY: float = 1.0          # seconds. частота работы главного цикла

# --- STYLES ---
HEAD_WIDTH = 35
HEAD_LINE_TYPE = "" #  либо "_"
FOOTER_WIDTH = 35
FOOTER_LINE_TYPE = "" #  либо "_"
EMO_SUCCESS = "🟢"
EMO_LOSE = "🔴"
EMO_ZERO = "⚪"
EMO_ORDER_FILLED = "🤞"