import asyncio
import aiohttp
from datetime import datetime
import time
from pprint import pprint
from typing import *
from a_settings import *
from b_context import BotContext
from c_di_container import DIContainer, setup_dependencies_first, setup_dependencies_second, setup_dependencies_third
from c_initializer import BaseDataInitializer, PositionVarsSetup
from c_log import ErrorHandler, log_time
from c_utils import PositionUtils, TimingUtils
from c_validators import TimeframeValidator, OrderValidator
from d_bapi import BinancePublicApi
from MANAGERS.online import WebSocketManager, NetworkManager
from MANAGERS.offline import KlinesCacheManager, WriteLogManager
from c_validators import validate_dataframe
from BUSINESS.position_control import Sync
from BUSINESS.order_patterns import RiskSet, HandleOrders
from BUSINESS.risk_orders_control import RiskOrdersControl
from BUSINESS.signals import SIGNALS, extract_signal_func_name
from d_bapi import BinancePrivateApi
from e_filter import CoinFilter
from TG.tg_notifier import TelegramNotifier
# from pprint import pprint
import traceback


SESSION_LIMIT = 15

def generate_bible_quote():
    random_bible_list = [
        "<<Благодать Господа нашего Иисуса Христа, и любовь Бога Отца, и общение Святаго Духа со всеми вами. Аминь.>>\n___(2-е Коринфянам 13:13)___",
        "<<Притом знаем, что любящим Бога, призванным по Его изволению, все содействует ко благу.>>\n___(Римлянам 8:28)___",
        "<<Спокойно ложусь я и сплю, ибо Ты, Господи, един даешь мне жить в безопасности.>>\n___(Пс 4:9)___"
    ]

    current_hour = datetime.now().hour
    if 6 <= current_hour < 12:
        return random_bible_list[0]
    elif 12 <= current_hour < 23:
        return random_bible_list[1]
    return random_bible_list[2]


import json

def save_to_json(data: Optional[dict], filename="data.json"):
    """
    Сохраняет словарь/список в JSON-файл с отступами.

    :param data: dict или list – данные для сохранения
    :param filename: str – путь до файла (например, '/home/user/data.json')
    """
    try:
        # Убедимся, что директория существует
        # os.makedirs(os.path.dirname(filename), exist_ok=False)

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Файл сохранён: {filename}")
    except Exception as e:
        print(f"Ошибка при сохранении: {e}")


# def load_from_json(filename: str = "data.json") -> Optional[Any]:
#     """
#     Загружает данные из JSON-файла.

#     :param filename: str – путь до файла (например, '/home/user/data.json')
#     :return: dict, list или None – данные из файла, либо None при ошибке
#     """
#     try:
#         with open(filename, 'r', encoding='utf-8') as f:
#             data = json.load(f)
#         print(f"Файл загружен: {filename}")
#         return data
#     except FileNotFoundError:
#         print(f"Файл не найден: {filename}")
#     except json.JSONDecodeError as e:
#         print(f"Ошибка чтения JSON ({filename}): {e}")
#     except Exception as e:
#         print(f"Ошибка при загрузке: {e}")

#     return None


async def get_cur_price(
        session,
        ws_price_data: dict,
        symbol: str,
        get_hot_price: callable,
    ):
    """
    Получение текущей цены символа.
    """
    cur_price = ws_price_data.get(symbol, {}).get("close")
    if not cur_price:
        return await get_hot_price(session, symbol)
    return cur_price


class Core:
    def __init__(self):
        self.context = BotContext()
        self.error_handler = ErrorHandler()
        self.container = DIContainer()       
        self.loaded_cache: dict = {}
        self.public_session: Optional[aiohttp.ClientSession] = None

    def _get_first_proxy(self) -> Optional[str]:
        """Берём proxy_url у первого пользователя, где он не None."""
        for user, details in self.context.total_settings.items():
            proxy_url = details.get("proxy_url")
            if proxy_url:
                return proxy_url
        return None

    async def _start_context(self):
        setup_dependencies_first(self.container, {
            "error_handler": self.error_handler,
            "context": self.context,
        })
        base_initializer: BaseDataInitializer = self.container.get("base_initializer")
        base_initializer.init_base_structure()
        self.pos_utils: PositionUtils = self.container.get("pos_utils")
        # //
        self.all_users = list(self.context.total_settings.keys())
        self.common_proxy_url = self._get_first_proxy()

        setup_dependencies_second(self.container, {
            "error_handler": self.error_handler,
            "context": self.context,
            "max_log_lines": MAX_LOG_LINES,
            "cron_cycle_interval": self.context.cron_cycle_interval,
            "cron_filter_interval": self.context.cron_filter_interval,
            "proxy_url": self.common_proxy_url
        })

        self.publuc_connector = NetworkManager(
            error_handler=self.error_handler,
            proxy_url=self.common_proxy_url, user_label="public")
        
        await self.publuc_connector.initialize_session()
        self.public_session: aiohttp.ClientSession = self.publuc_connector.session

        self.binance_public: BinancePublicApi = self.container.get("binance_public")
        self.context.symbol_info = await self.binance_public.get_exchange_info(self.public_session)
        position_vars_setup: PositionVarsSetup = self.container.get("position_vars_setup")
        position_vars_setup.setup_pos_vars()
        # //
        
        await asyncio.gather(*[self._init_all_users_sessions(user_name) for user_name in self.all_users])
        # //
        self.websocket_manager: WebSocketManager = self.container.get("websocket_manager")
        self.time_frame_validator: TimeframeValidator = self.container.get("time_frame_validator")

        setup_dependencies_third(self.container, {
            "error_handler": self.error_handler,
            "context": self.context,
            "get_klines": self.binance_public.get_klines,
            "time_frame_validator": self.time_frame_validator,
            "pos_utils": self.pos_utils
        })
        self.klines_cache_manager: KlinesCacheManager = self.container.get("klines_cache_manager")
        self.signals: SIGNALS = self.container.get("signals")        
        self.cron_cycle: TimingUtils = self.container.get("cron_cycle")
        self.cron_filter: TimingUtils = self.container.get("cron_filter")     
        self.order_validator: OrderValidator = self.container.get("order_validator")
        self.risk_order_control: RiskOrdersControl = self.container.get("risk_order_control")
        # # ///

        self.risk_order_patterns = RiskSet(
            context=self.context,
            error_handler=self.error_handler,
            validate=self.order_validator
        )

        self.write_log: WriteLogManager = self.container.get("write_log_manager")
        loaded_cache = await self.write_log.load_cache(file_name="pos_cache.pkl") \
            if USE_CACHE and await self.write_log.cache_exists(file_name="pos_cache.pkl") else {}
        # pprint(f"loaded_cache: {loaded_cache}")
        # save_to_json(loaded_cache)

        self.handle_odrers = HandleOrders(
            context=self.context,
            error_handler=self.error_handler,
            pos_utils=self.pos_utils,
            risk_set=self.risk_order_patterns,
            get_hot_price=self.binance_public.get_hot_price,
            get_cur_price=get_cur_price
        )

        self.notifier = TelegramNotifier(             
            token=TG_BOT_TOKEN,
            chat_ids=[TG_BOT_ID,],
            context=self.context,
            info_handler=self.error_handler 
        )

        self.sync = Sync(
            context=self.context,
            error_handler=self.error_handler,
            loaded_cache=loaded_cache,
            write_cache=self.write_log.write_cache,
            set_pos_defaults=position_vars_setup.set_pos_defaults,
            cancel_all_risk_orders=self.risk_order_patterns.cancel_all_risk_orders,
            preform_message=self.notifier.preform_message,
            use_cache=USE_CACHE,
            positions_update_frequency=POS_UPDATE_FREQUENCY
        )

        self.filter = CoinFilter(
            context=self.context, 
            error_handler=self.error_handler, 
            binance_public=self.binance_public
        )

        self.error_handler.wrap_foreign_methods(self)

    async def _init_all_users_sessions(self, user_name: str) -> None:
        user_details: dict = self.context.total_settings[user_name]
        proxy_url = user_details.get("proxy_url", None)

        connector = NetworkManager(error_handler=self.error_handler, proxy_url=proxy_url, user_label=user_name)
        await connector.initialize_session()
        if not await connector.validate_session():
            self.error_handler.debug_error_notes(f'[ERROR][{user_name}]: проблемы с инициализацией сессии')
            raise RuntimeError(f"Failed to initialize session for {user_name}")

        keys = user_details["keys"]

        binance_client = BinancePrivateApi(
            error_handler=self.error_handler,
            api_key=keys["BINANCE_API_PUBLIC_KEY"],
            api_secret=keys["BINANCE_API_PRIVATE_KEY"],
            proxy_url=proxy_url,
            user_label=user_name,
        )

        self.context.user_contexts[user_name] = {
            "connector": connector,
            "binance_client": binance_client,
        }

    async def refresh_connector(self, user_name: str) -> bool:
        """
        Пересоздаёт NetworkManager и обновляет connector в user_contexts,
        только если это действительно нужно (при реальном сбое сессии).
        Возвращает True, если сессия в порядке.
        """
        connector: NetworkManager = self.context.user_contexts[user_name]["connector"]
        is_valid, was_reconnected = await connector.validate_session()

        if is_valid and not was_reconnected:
            # Всё норм, сессия рабочая, ничего не меняем
            return True

        if not is_valid:
            self.error_handler.debug_error_notes(f"[ERROR][{user_name}]: не удалось восстановить старый connector")

        # Пересоздаём только если реальный фейл или reconnected (для свежей сессии)
        user_details: dict = self.context.total_settings[user_name]
        proxy_url = user_details.get("proxy_url")

        new_connector = NetworkManager(
            error_handler=self.error_handler,
            proxy_url=proxy_url,
            user_label=user_name
        )
        await new_connector.initialize_session()

        new_valid, _ = await new_connector.validate_session()
        if not new_valid:
            self.error_handler.debug_error_notes(f"[ERROR][{user_name}]: не удалось инициализировать новый connector")
            return False

        self.context.user_contexts[user_name]["connector"] = new_connector
        return True

    async def _quit_all_users_sessions(self, user_name: str) -> None:
        connector: NetworkManager = self.context.user_contexts[user_name]["connector"]
        await connector.shutdown_session()

    async def _run(self):
        print(f"\n{generate_bible_quote()}")
        print(f"Время старта: {log_time()}")

        await self._start_context()

        if not await self.publuc_connector.validate_session():
            self.error_handler.debug_error_notes(f'[ERROR][public]: проблемы с инициализацией сессии')
            raise RuntimeError(f"Failed to initialize session for 'public'")

        check_sessions_counter = 0        
        update_positions_counter = 0
        self.sessions_ok = True

        if not self.context.fetch_symbols:
            print("Нет ни одного символа для торговли.")
            self.context.stop_bot = True
            return

        # # # set hedg mode for all users:
        # await self.handle_odrers.set_hedge_mode_for_all_users(
        #     all_users=self.all_users,
        #     enable_hedge=True
        # )
        
        # # // web socket start
        await self.websocket_manager.sync_ws_streams(list(self.context.fetch_symbols))
        # await asyncio.sleep(10)
        while not self.context.stop_bot:
            # ждём пока у каждого символа будет "close" != None
            if all(
                self.context.ws_price_data.get(s, {}).get("close") is not None
                for s in self.context.fetch_symbols
            ):
                break
            await asyncio.sleep(0.1)

        # pprint(self.context.ws_price_data)
        # return

        # pprint(self.context.symbol_info)
        # pprint(self.context.position_vars)

        asyncio.create_task(self.sync.positions_flow_manager())

        while not self.context.stop_bot and not all(self.context.first_update_done.get(user_name, False) for user_name in self.all_users):
            await asyncio.sleep(0.25)

        print("Начало основного цикла...")

        # ---- Обновляем инструменты каждые 300 секунд ---
        instrume_update_interval = 300.0
        # --- пишем логи каждые 5 секунд ---
        write_logs_interval = 5.0

        last_instrume_time = time.monotonic()
        last_write_logs_time = time.monotonic()      

        while not self.context.stop_bot:
            try:
                check_sessions_counter += 1
                update_positions_counter += 1
                users_tasks = []

                if check_sessions_counter >= SESSION_LIMIT:
                    check_sessions_counter = 0

                    # проверяем публичку
                    if not await self.publuc_connector.validate_session():
                        self.error_handler.debug_error_notes(f'[ERROR][public]: проблемы с обновлением сессии')

                    # рефрешим приватки
                    result = await asyncio.gather(*[self.refresh_connector(user_name) for user_name in self.all_users])
                    if not all(result):
                        self.error_handler.debug_info_notes("❌ Не все сессии восстановлены. Ожидаем перед повтором...")
                        await asyncio.sleep(60)
                        continue

                if self.cron_filter.time_scheduler() or self.context.first_iter:
                    # print("self.cron_filter.time_scheduler()")
                    await asyncio.gather(*[self.filter.apply_filter_settings(self.public_session, user_name, self.context.fetch_symbols) for user_name in self.all_users])
                    # ✅ Печатаем один раз после обработки всех юзеров
                    # self.filter.print_report()

                # //signal block:
                interval_completed = self.cron_cycle.time_scheduler()
                long_count, short_count, active_symbols = self.pos_utils.count_active_symbols(
                    self.context.position_vars
                )

                should_get_klines = self.klines_cache_manager.get_klines_scheduler(active_symbols, interval_completed)

                if should_get_klines or self.context.first_iter:   
                    # print("should_get_klines")
                    if self.context.ukik_suffics_data.get("klines_lim") > 0:       
                        await asyncio.sleep(WAIT_CLOSE_CANDLE)
                        await self.klines_cache_manager.total_klines_handler(self.public_session)
                        # print(self.context.klines_data_cache)
                
                if not (should_get_klines or active_symbols) and not self.pos_utils.has_any_failed_position():
                    continue

                for user_name in self.all_users:
                    core_settings: Dict = self.context.total_settings[user_name]["core"]
                    connector: NetworkManager = self.context.user_contexts[user_name]["connector"]
                    binance_client: BinancePrivateApi = self.context.user_contexts[user_name]["binance_client"]
                    strategies: Dict = self.context.position_vars[user_name]  # ← стратегии
                    config_direction: List = core_settings.get("direction")

                    for strategy_number, (strategy_name, strategy_data) in enumerate(strategies.items(), start=1):
                        ind_suffics = f"{user_name}_{strategy_number}"

                        for symbol, symbol_pos_data in strategy_data.items():
                            # print(symbol)
                            for position_side in ("LONG", "SHORT"):

                                if extract_signal_func_name(strategy_name) == "cron":                                    
                                    long_limit = core_settings.get("long_positions_limit", float("inf"))
                                    short_limit = core_settings.get("short_positions_limit", float("inf"))
                                    if active_symbols and len(active_symbols) >= max(long_limit, short_limit):
                                        if symbol not in active_symbols:
                                            continue                                        

                                signal_repl = self.signals.get_signal(
                                    user_name,
                                    strategy_name,          
                                    symbol,
                                    position_side,
                                    config_direction,
                                    ind_suffics,
                                    long_count,
                                    short_count
                                )

                                if not signal_repl:
                                    continue

                                open_signal, avg_signal, close_signal, reverse_pos_side = signal_repl
                                # print(f"open_signal={open_signal}, avg_signal={avg_signal}, close_signal={close_signal}")

                                if open_signal:
                                    if reverse_pos_side:
                                        opposite = {"LONG": "SHORT", "SHORT": "LONG"}
                                        position_side = opposite[position_side]

                                    debug_label = f"{user_name}_{symbol}_{position_side}"
                                    self.error_handler.trades_info_notes(
                                        f"[{debug_label}]. 🚀 Открываем позицию по сигналу! ",
                                        True
                                    )

                                    strategy_settings = self.context.strategy_notes[strategy_name][position_side]
                                    volume_rate = strategy_settings.get("entry_conditions").get("grid_orders")[0].get("volume")
                                    symbol_pos_data.get(position_side)["process_volume"] = volume_rate /  100
                                    users_tasks.append(self.signals.compose_signals(
                                        user_name=user_name,
                                        strategy_name=strategy_name,
                                        symbol=symbol,
                                        position_side=position_side,
                                        status="is_opening",
                                        client_session=connector.session,
                                        binance_client=binance_client
                                    ))

                                if symbol not in active_symbols:
                                    continue

                                users_tasks.append(self.risk_order_control.risk_symbol_monitoring(                                  
                                    user_name=user_name,
                                    strategy_name=strategy_name,
                                    symbol=symbol,
                                    position_side=position_side,
                                    avg_signal=avg_signal,
                                    close_signal=close_signal,
                                    compose_signals=self.signals.compose_signals,
                                    client_session=connector.session,
                                    binance_client=binance_client
                                ))

                users_tasks = list(filter(None, users_tasks))
                if users_tasks:
                    await self.handle_odrers.compose_trade_instruction(task_list=users_tasks)

            except Exception as ex:
                tb = traceback.format_exc()
                self.error_handler.debug_error_notes(
                    f"[_run.main.py]: Ошибка при обработке: {ex}/{tb}\n",
                    is_print=True
                )

            finally:   
                try:
                    if self.context.report_list:
                        await self.notifier.send_report_batches(batch_size=1)  
                except Exception as e:
                    err_msg = f"[ERROR] main finally block: {e}\n" + traceback.format_exc()
                    self.error_handler.debug_error_notes(err_msg, is_print=True)      

                now = time.monotonic()
                # if now - last_instrume_time >= instrume_update_interval:
                #     try:
                #         self.context.symbol_info = await self.binance_public.get_exchange_info(self.public_session)
                #         if not self.context.symbol_info:
                #             self.error_handler.debug_error_notes(f"[ERROR] Failed to fetch instruments: {e}", is_print=True)

                #     except Exception as e:
                #         self.error_handler.debug_error_notes(f"[ERROR] Failed to fetch instruments: {e}", is_print=True)
                #     last_instrume_time = now

                if now - last_write_logs_time >= write_logs_interval:
                    try:
                        await self.write_log.write_logs()
                    except Exception as e:
                        self.error_handler.debug_error_notes(f"Ошибка при записи логов: {e}")
                    last_write_logs_time = now

                self.context.first_iter = False
                await asyncio.sleep(MAIN_CYCLE_FREQUENCY)
                # print("Tik")


async def main():
    instance = Core()
    try:
        await instance._run()
    except asyncio.CancelledError:
        print("🚩 Асинхронная задача была отменена.")
    except KeyboardInterrupt:
        print("\n⛔ Остановка по Ctrl+C")
    # except Exception as e:
    #     print(f"\n❌ Ошибка: {type(e).__name__} — {e}")
    finally:
        if USE_CACHE:
            try:
                await instance.write_log.write_cache(
                    data_dict=instance.context.position_vars,
                    file_name="pos_cache.pkl"
                )
            except Exception as e:
                print(f"[SYNC][ERROR] write_cache: {e}")

        instance.context.stop_bot = True
        await asyncio.gather(*[instance._quit_all_users_sessions(user_name) for user_name in instance.all_users])
        await instance.publuc_connector.shutdown_session()  # ← добавь это
        print("Сессии закрываются...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


# git add . 
# git commit -m "fix martin reverse 4"
# git push -u origin volfUs


# # убедились, что права уже установлены (вы это сделали)
# chmod 600 ssh_key

# # запустить агент (если он не запущен) и добавить ключ из текущей директории
# eval "$(ssh-agent -s)" && ssh-add ./ssh_key

# ssh-add -l        # выведет список добавленных ключей или "The agent has no identities"

# ssh -T git@github.com
