import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from .logger import logger
from .telegram_notifier import TelegramNotifier
from .config_manager import ConfigManager

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