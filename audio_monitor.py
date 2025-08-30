#!/usr/bin/env python3
"""
Plex Audio Monitor - Автоматический мониторинг и Telegram уведомления
Запускается как служба Windows или в фоне для периодической проверки новых файлов

Автор: Assistant
Версия: 1.0
"""

import os
import sys
import json
import time
import logging
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import configparser
import signal

# Для Telegram уведомлений
try:
    from telegram import Bot
    from telegram.error import TelegramError

    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("Внимание: telegram библиотека не установлена. Установите: pip install python-telegram-bot")

# Для создания Windows службы
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    WINDOWS_SERVICE = True
except ImportError:
    WINDOWS_SERVICE = False

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audio_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ConfigManager:
    """Менеджер конфигурации"""

    DEFAULT_CONFIG = """
[General]
# Директория для мониторинга
watch_directory = E:\\Download\\Movie
# Интервал проверки в секундах (300 = 5 минут)
check_interval = 300
# Максимальная глубина сканирования
max_depth = 2
# Удалять оригиналы после конвертации
delete_original = false
# Путь к основному скрипту конвертации
converter_script = audio_converter.py

[FFmpeg]
# Путь к ffmpeg и ffprobe
ffmpeg_path = ffmpeg
ffprobe_path = ffprobe
# Параметры конвертации
audio_codec = aac
audio_bitrate = 192k
audio_sample_rate = 48000

[Telegram]
# Включить Telegram уведомления
enabled = false
# Bot Token (получите у @BotFather)
bot_token = YOUR_BOT_TOKEN_HERE
# Chat ID (получите у @userinfobot)
chat_id = YOUR_CHAT_ID_HERE
# Типы уведомлений
notify_on_start = true
notify_on_conversion = true
notify_on_no_english = true
notify_on_error = true
notify_summary = true

[FileTypes]
# Расширения видеофайлов для обработки
extensions = .mp4,.mkv,.avi,.mov,.m4v,.wmv,.flv,.webm

[Advanced]
# Минимальный размер файла в МБ для обработки
min_file_size_mb = 100
# Игнорировать файлы старше N дней (0 = не игнорировать)
ignore_older_than_days = 0
# Создавать резервные копии
create_backup = true
"""

    def __init__(self, config_file: str = 'monitor_config.ini'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        """Загрузка конфигурации"""
        if not Path(self.config_file).exists():
            self.create_default_config()

        self.config.read(self.config_file, encoding='utf-8')
        logger.info(f"Конфигурация загружена из: {self.config_file}")

    def create_default_config(self):
        """Создание файла конфигурации по умолчанию"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write(self.DEFAULT_CONFIG.strip())
        logger.info(f"Создан файл конфигурации: {self.config_file}")
        logger.info("Отредактируйте его перед запуском!")

    def get(self, section: str, option: str, fallback=None):
        """Получение значения из конфигурации"""
        try:
            return self.config.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def getboolean(self, section: str, option: str, fallback=False):
        """Получение булевого значения"""
        try:
            return self.config.getboolean(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def getint(self, section: str, option: str, fallback=0):
        """Получение целочисленного значения"""
        try:
            return self.config.getint(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = None

        if TELEGRAM_AVAILABLE:
            try:
                self.bot = Bot(token=bot_token)
                logger.info("Telegram бот инициализирован")
            except Exception as e:
                logger.error(f"Ошибка инициализации Telegram бота: {e}")

    async def send_message(self, text: str, parse_mode: str = 'HTML'):
        """Отправка сообщения"""
        if not self.bot:
            return False

        try:
            # Разбиваем длинные сообщения
            max_length = 4096
            if len(text) <= max_length:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode
                )
            else:
                # Разбиваем на части
                parts = [text[i:i + max_length] for i in range(0, len(text), max_length)]
                for part in parts:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=part,
                        parse_mode=parse_mode
                    )
                    await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

            return True
        except Exception as e:
            logger.error(f"Ошибка отправки Telegram сообщения: {e}")
            return False

    async def send_file(self, file_path: Path, caption: str = None):
        """Отправка файла"""
        if not self.bot or not file_path.exists():
            return False

        try:
            with open(file_path, 'rb') as f:
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=f,
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки файла в Telegram: {e}")
            return False


class AudioMonitor:
    """Основной класс мониторинга"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.running = False
        self.notifier = None
        self.processed_files = set()
        self.stats = {
            'total_processed': 0,
            'converted': 0,
            'errors': 0,
            'no_english': 0
        }

        # Инициализация Telegram
        if self.config.getboolean('Telegram', 'enabled'):
            bot_token = self.config.get('Telegram', 'bot_token')
            chat_id = self.config.get('Telegram', 'chat_id')

            if bot_token and chat_id and bot_token != 'YOUR_BOT_TOKEN_HERE':
                self.notifier = TelegramNotifier(bot_token, chat_id)
            else:
                logger.warning("Telegram настроен некорректно")

        # Загрузка истории обработанных файлов
        self.load_processed_files()

    def load_processed_files(self):
        """Загрузка списка обработанных файлов"""
        history_file = Path('processed_files.json')
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_files = set(data.get('files', []))
                    self.stats = data.get('stats', self.stats)
                logger.info(f"Загружена история: {len(self.processed_files)} файлов")
            except Exception as e:
                logger.error(f"Ошибка загрузки истории: {e}")

    def save_processed_files(self):
        """Сохранение списка обработанных файлов"""
        history_file = Path('processed_files.json')
        try:
            data = {
                'files': list(self.processed_files),
                'stats': self.stats,
                'last_update': datetime.now().isoformat()
            }
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}")

    def find_new_files(self, directory: Path) -> List[Path]:
        """Поиск новых видеофайлов"""
        new_files = []
        extensions = self.config.get('FileTypes', 'extensions', '.mp4,.mkv').split(',')
        min_size_mb = self.config.getint('Advanced', 'min_file_size_mb', 100)
        min_size_bytes = min_size_mb * 1024 * 1024
        ignore_days = self.config.getint('Advanced', 'ignore_older_than_days', 0)
        
        logger.info(f"Поиск файлов в: {directory}")
        logger.info(f"Расширения: {extensions}")
        logger.info(f"Минимальный размер: {min_size_mb} МБ")
        logger.info(f"Игнорировать старше: {ignore_days} дней")

        # Определяем минимальную дату модификации
        if ignore_days > 0:
            min_date = datetime.now() - timedelta(days=ignore_days)
        else:
            min_date = None

        def scan_dir(path: Path, depth: int = 0):
            max_depth = self.config.getint('General', 'max_depth', 2)
            if depth > max_depth:
                logger.debug(f"Достигнута максимальная глубина {max_depth} для: {path}")
                return

            try:
                logger.info(f"Сканируем директорию (глубина {depth}): {path}")
                items = list(path.iterdir())
                logger.info(f"Найдено элементов: {len(items)}")
                
                for item in items:
                    if item.is_dir():
                        logger.debug(f"Найдена поддиректория: {item.name}")
                        scan_dir(item, depth + 1)
                    elif item.is_file():
                        logger.debug(f"Найден файл: {item.name} ({item.suffix.lower()})")
                        
                        # Проверяем расширение
                        if item.suffix.lower() not in extensions:
                            logger.debug(f"Пропускаем файл (неподходящее расширение): {item.name}")
                            continue

                        # Проверяем размер
                        file_size_mb = item.stat().st_size / (1024 * 1024)
                        if item.stat().st_size < min_size_bytes:
                            logger.debug(f"Пропускаем файл (маленький размер {file_size_mb:.1f} МБ): {item.name}")
                            continue

                        # Проверяем дату модификации
                        if min_date:
                            mtime = datetime.fromtimestamp(item.stat().st_mtime)
                            if mtime < min_date:
                                logger.debug(f"Пропускаем файл (старый): {item.name}")
                                continue

                        # Проверяем, не обработан ли файл ранее
                        if str(item) not in self.processed_files:
                            logger.info(f"Найден новый файл для обработки: {item.name} ({file_size_mb:.1f} МБ)")
                            new_files.append(item)
                        else:
                            logger.debug(f"Файл уже обработан: {item.name}")
            except PermissionError:
                logger.warning(f"Нет доступа к: {path}")
            except Exception as e:
                logger.error(f"Ошибка сканирования {path}: {e}")

        scan_dir(directory)
        return new_files

    async def process_file(self, file_path: Path) -> Dict:
        """Обработка одного файла"""
        result = {
            'file': str(file_path),
            'status': 'unknown',
            'timestamp': datetime.now().isoformat()
        }

        try:
            # Запускаем основной скрипт конвертации
            converter_script = self.config.get('General', 'converter_script', 'audio_converter.py')
            delete_flag = '--delete-original' if self.config.getboolean('General', 'delete_original') else ''

            cmd = list(filter(None, [
                sys.executable,  # Python интерпретатор
                converter_script,
                str(file_path.parent),  # Директория файла
                delete_flag
            ]))  # Убираем пустые элементы

            logger.info(f"Обрабатываем: {file_path.name}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                result['status'] = 'success'
                self.stats['converted'] += 1

                # Отправляем уведомление
                if self.notifier and self.config.getboolean('Telegram', 'notify_on_conversion'):
                    message = f"✅ <b>Файл конвертирован</b>\n\n📁 {file_path.name}"
                    await self.notifier.send_message(message)
            else:
                result['status'] = 'error'
                result['error'] = stderr.decode('utf-8', errors='ignore')
                self.stats['errors'] += 1

                # Отправляем уведомление об ошибке
                if self.notifier and self.config.getboolean('Telegram', 'notify_on_error'):
                    message = f"❌ <b>Ошибка конвертации</b>\n\n📁 {file_path.name}\n\n{result['error'][:500]}"
                    await self.notifier.send_message(message)

        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            self.stats['errors'] += 1
            logger.error(f"Ошибка обработки {file_path}: {e}")

        # Добавляем в обработанные
        self.processed_files.add(str(file_path))
        self.stats['total_processed'] += 1
        self.save_processed_files()

        return result

    async def monitor_loop(self):
        """Основной цикл мониторинга"""
        watch_dir_str = self.config.get('General', 'watch_directory')
        watch_dir_abs = os.path.abspath(watch_dir_str)
        check_interval = self.config.getint('General', 'check_interval', 300)

        # Проверяем существование директории
        if not os.path.exists(watch_dir_abs):
            logger.error(f"Директория не существует: {watch_dir_abs}")
            logger.info(f"Попытка создать директорию: {watch_dir_abs}")
            try:
                os.makedirs(watch_dir_abs, exist_ok=True)
                logger.info(f"Директория создана: {watch_dir_abs}")
            except Exception as e:
                logger.error(f"Не удалось создать директорию {watch_dir_abs}: {e}")
                logger.error("Мониторинг остановлен")
                return

        if not os.path.isdir(watch_dir_abs):
            logger.error(f"Путь не является директорией: {watch_dir_abs}")
            return

        watch_dir = Path(watch_dir_abs)
        logger.info(f"Начинаем мониторинг: {watch_dir}")
        logger.info(f"Интервал проверки: {check_interval} секунд")

        # Отправляем уведомление о запуске
        if self.notifier and self.config.getboolean('Telegram', 'notify_on_start'):
            message = f"🚀 <b>Мониторинг запущен</b>\n\n📁 Директория: {watch_dir}\n⏱ Интервал: {check_interval}с"
            await self.notifier.send_message(message)

        self.running = True
        last_summary_time = datetime.now()
        last_check_time = datetime.now() - timedelta(seconds=check_interval)  # Принудительная проверка при запуске

        while self.running:
            try:
                current_time = datetime.now()
                
                # Проверяем, пора ли сканировать файлы
                if (current_time - last_check_time).total_seconds() >= check_interval:
                    # Ищем новые файлы
                    new_files = self.find_new_files(watch_dir)

                    if new_files:
                        logger.info(f"Найдено новых файлов: {len(new_files)}")

                        for file_path in new_files:
                            if not self.running:
                                break

                            await self.process_file(file_path)
                            # Короткая пауза между файлами с проверкой флага
                            for _ in range(20):  # 2 секунды = 20 * 0.1
                                if not self.running:
                                    break
                                await asyncio.sleep(0.1)
                    else:
                        logger.info("Новых файлов для обработки не найдено")
                    
                    last_check_time = current_time

                # Отправляем сводку раз в час
                if self.notifier and self.config.getboolean('Telegram', 'notify_summary'):
                    if (current_time - last_summary_time).total_seconds() >= 3600:
                        await self.send_summary()
                        last_summary_time = current_time

                # Короткий sleep с частой проверкой флага остановки
                await asyncio.sleep(1)  # Проверяем каждую секунду

            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                # Короткая пауза при ошибке с проверкой флага
                for _ in range(30):  # 30 секунд = 30 * 1
                    if not self.running:
                        break
                    await asyncio.sleep(1)

    async def send_summary(self):
        """Отправка сводки в Telegram"""
        if not self.notifier:
            return

        message = f"""📊 <b>Статистика работы</b>

📁 Обработано файлов: {self.stats['total_processed']}
✅ Конвертировано: {self.stats['converted']}
⚠️ Без английских дорожек: {self.stats['no_english']}
❌ Ошибок: {self.stats['errors']}

⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""

        await self.notifier.send_message(message)

    def stop(self):
        """Остановка мониторинга"""
        logger.info("Останавливаем мониторинг...")
        self.running = False


class AudioMonitorService(win32serviceutil.ServiceFramework):
    """Windows служба для мониторинга"""

    _svc_name_ = "PlexAudioMonitor"
    _svc_display_name_ = "Plex Audio Converter Monitor"
    _svc_description_ = "Автоматическая конвертация 5.1 аудио в стерео для Plex"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.monitor = None
        self.loop = None

    def SvcStop(self):
        """Остановка службы"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

        if self.monitor:
            self.monitor.stop()

        # Даем время на корректное завершение
        import time
        time.sleep(2)

        if self.loop and self.loop.is_running():
            # Планируем остановку цикла
            self.loop.call_soon_threadsafe(self.loop.stop)

    def SvcDoRun(self):
        """Запуск службы"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )

        # Создаем конфигурацию и мониторинг
        config = ConfigManager()
        self.monitor = AudioMonitor(config)

        # Запускаем асинхронный цикл
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            # Создаем задачу для мониторинга
            monitor_task = self.loop.create_task(self.monitor.monitor_loop())
            
            # Запускаем цикл до получения сигнала остановки
            while not win32event.WaitForSingleObject(self.hWaitStop, 1000) == win32event.WAIT_OBJECT_0:
                if monitor_task.done():
                    break
                    
            # Отменяем задачу мониторинга
            if not monitor_task.done():
                monitor_task.cancel()
                try:
                    self.loop.run_until_complete(monitor_task)
                except asyncio.CancelledError:
                    pass
                    
        except Exception as e:
            servicemanager.LogErrorMsg(f"Ошибка службы: {e}")
        finally:
            if self.loop and not self.loop.is_closed():
                self.loop.close()


async def main():
    """Главная функция для консольного запуска"""
    # Загружаем конфигурацию
    config = ConfigManager()

    # Проверяем конфигурацию
    if config.get('General', 'watch_directory') == 'C:\\Download':
        logger.warning("Используется директория по умолчанию. Отредактируйте monitor_config.ini!")

    # Создаем мониторинг
    monitor = AudioMonitor(config)

    # Обработка сигналов для корректной остановки
    def signal_handler(sig, frame):
        logger.info(f"Получен сигнал остановки: {sig}")
        monitor.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Запускаем мониторинг
    try:
        await monitor.monitor_loop()
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем (Ctrl+C)")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
    finally:
        logger.info("Завершение работы мониторинга...")
        monitor.stop()
        
        # Отправляем уведомление о завершении
        if monitor.notifier and monitor.config.getboolean('Telegram', 'notify_on_start'):
            try:
                message = "🛑 <b>Мониторинг остановлен</b>"
                await monitor.notifier.send_message(message)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о завершении: {e}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Управление Windows службой
        if WINDOWS_SERVICE:
            if sys.argv[1] == 'install':
                win32serviceutil.InstallService(
                    AudioMonitorService,
                    AudioMonitorService._svc_name_,
                    AudioMonitorService._svc_display_name_
                )
                print(f"Служба {AudioMonitorService._svc_display_name_} установлена")
            elif sys.argv[1] == 'remove':
                win32serviceutil.RemoveService(AudioMonitorService._svc_name_)
                print(f"Служба {AudioMonitorService._svc_display_name_} удалена")
            elif sys.argv[1] == 'start':
                win32serviceutil.StartService(AudioMonitorService._svc_name_)
                print(f"Служба {AudioMonitorService._svc_display_name_} запущена")
            elif sys.argv[1] == 'stop':
                win32serviceutil.StopService(AudioMonitorService._svc_name_)
                print(f"Служба {AudioMonitorService._svc_display_name_} остановлена")
            else:
                print("Использование: monitor.py [install|remove|start|stop]")
        else:
            print("Windows службы не поддерживаются (установите pywin32)")
    else:
        # Консольный запуск
        asyncio.run(main())
