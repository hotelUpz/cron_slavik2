# c_di_container.py
from typing import *
from b_context import BotContext
from c_initializer import BaseDataInitializer, PositionVarsSetup
from c_log import ErrorHandler
from c_utils import PositionUtils, TimingUtils
from c_validators import TimeframeValidator, OrderValidator
from d_bapi import BinancePublicApi
from MANAGERS.online import WebSocketManager
from MANAGERS.offline import KlinesCacheManager, WriteLogManager
from BUSINESS.signals import SIGNALS
from BUSINESS.risk_orders_control import RiskOrdersControl


class DIContainer:
    def __init__(self):
        self._factories = {}
        self._instances = {}

    def register(self, key: str, factory: callable, singleton: bool = False):
        self._factories[key] = {
            "factory": factory,
            "singleton": singleton,
        }

    def get(self, key: str):
        if key in self._instances:
            return self._instances[key]

        if key not in self._factories:
            raise KeyError(f"Dependency '{key}' is not registered.")

        factory_info = self._factories[key]
        instance = factory_info["factory"]()

        if factory_info["singleton"]:
            self._instances[key] = instance

        return instance
    

def setup_dependencies_first(container: DIContainer, config: dict):
    error_handler: ErrorHandler = config.get("error_handler")
    context: BotContext = config.get("context")    
    container.register("pos_utils", lambda: PositionUtils(context, error_handler), singleton=True)
    pos_utils = container.get("pos_utils")
    container.register("base_initializer", lambda: BaseDataInitializer(
        context, 
        error_handler,
        pos_utils
        ),
        singleton=True
    )
    container.register("position_vars_setup", lambda: PositionVarsSetup(
        context, 
        error_handler,
        pos_utils
        ),
        singleton=True
    )

def setup_dependencies_second(container, config: dict):    
    error_handler: ErrorHandler = config.get("error_handler")
    context: BotContext = config.get("context")
    proxy_url: Optional[str] = config.get("proxy_url")
    container.register("cron_cycle", lambda: TimingUtils(
        error_handler,
        config.get("cron_cycle_interval")
        )
    )
    container.register("cron_filter", lambda: TimingUtils(
        error_handler,
        config.get("cron_filter_interval")
        )
    )
    container.register("write_log_manager", lambda: WriteLogManager(
        error_handler,
        config.get("max_log_lines")
        ), singleton=True
    )
    container.register("websocket_manager", lambda: WebSocketManager(
        context=context,
        error_handler=error_handler,
        proxy_url=proxy_url
    ), singleton=True)
    container.register("time_frame_validator", lambda: TimeframeValidator(error_handler), singleton=True)
    container.register("order_validator", lambda: OrderValidator(error_handler), singleton=True)    
    container.register("binance_public", lambda: BinancePublicApi(error_handler, None), singleton=True)

def setup_dependencies_third(container, config: dict):
    error_handler: ErrorHandler = config.get("error_handler")
    context: BotContext = config.get("context")
    get_klines: callable = config.get("get_klines")
    time_frame_validator: TimeframeValidator = config.get("time_frame_validator")
    pos_utils: PositionUtils = config.get("pos_utils")
    container.register("klines_cache_manager", lambda: KlinesCacheManager(
        context,
        error_handler,
        get_klines
        ),
        singleton=True
    )
    container.register("signals", lambda: SIGNALS(
        context,
        error_handler,
        time_frame_validator
        ),
        singleton=True
    )

    container.register("risk_order_control", lambda: RiskOrdersControl(
        context,
        error_handler,
        pos_utils,
        ),
        singleton=True
    )