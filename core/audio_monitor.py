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
            logger.info(f"Начинаем обработку: {file_path.name}")
            
            # Анализируем файл и отправляем уведомление о начале обработки
            if self.notifier and self.config.getboolean('Telegram', 'notify_on_processing'):
                file_info = await self.analyze_file_info(file_path)
                message = f"🔄 Начинаем обработку файла"
                await self.notifier.send_file_info_notification(file_info, message)
            
            # Запускаем основной скрипт конвертации
            converter_script = self.config.get('General', 'converter_script', 'audio_converter.py')
            delete_flag = '--delete-original' if self.config.getboolean('General', 'delete_original') else ''

            cmd = list(filter(None, [
                sys.executable,  # Python интерпретатор
                converter_script,
                str(file_path.parent),  # Директория файла
                delete_flag
            ]))  # Убираем пустые элементы

            logger.info(f"Запускаем конвертацию: {file_path.name}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                result['status'] = 'success'
                self.stats['converted'] += 1

                # Отправляем визуальное уведомление о успешной конвертации
                if self.notifier and self.config.getboolean('Telegram', 'notify_on_conversion'):
                    conversion_info = {
                        'status': 'success',
                        'filename': file_path.name,
                        'source_track': {
                            'channels': 6,
                            'language': 'eng',
                            'codec': 'unknown'
                        },
                        'target_track': {
                            'channels': 2,
                            'language': 'eng',
                            'codec': 'aac'
                        },
                        'duration': result.get('duration', 0),
                        'output_size': file_path.stat().st_size if file_path.exists() else 0
                    }
                    await self.notifier.send_conversion_notification(conversion_info)
            else:
                result['status'] = 'error'
                result['error'] = stderr.decode('utf-8', errors='ignore')
                self.stats['errors'] += 1

                # Отправляем визуальное уведомление об ошибке
                if self.notifier and self.config.getboolean('Telegram', 'notify_on_error'):
                    conversion_info = {
                        'status': 'error',
                        'filename': file_path.name,
                        'source_track': {
                            'channels': 6,
                            'language': 'eng',
                            'codec': 'unknown'
                        },
                        'error': result['error'][:200]
                    }
                    await self.notifier.send_conversion_notification(conversion_info)

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

    async def analyze_file_info(self, file_path: Path) -> Dict:
        """Анализ информации о файле для уведомления"""
        try:
            import subprocess
            import json
            
            # Используем ffprobe для получения информации о файле
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"Не удалось проанализировать файл {file_path.name}")
                return self._get_basic_file_info(file_path)
            
            data = json.loads(result.stdout)
            
            # Извлекаем информацию о файле
            file_info = {
                'name': file_path.name,
                'size': file_path.stat().st_size,
                'audio_tracks': []
            }
            
            # Получаем информацию о формате
            format_info = data.get('format', {})
            if 'duration' in format_info:
                file_info['duration'] = float(format_info['duration'])
            
            # Анализируем потоки
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    # Информация о видео
                    width = stream.get('width')
                    height = stream.get('height')
                    if width and height:
                        file_info['resolution'] = f"{width}x{height}"
                
                elif stream.get('codec_type') == 'audio':
                    # Информация об аудио дорожках
                    track = {
                        'index': stream.get('index', 0),
                        'codec': stream.get('codec_name', 'unknown'),
                        'channels': stream.get('channels', 0),
                        'language': 'unknown'
                    }
                    
                    # Извлекаем язык из тегов
                    tags = stream.get('tags', {})
                    for key, value in tags.items():
                        if key.lower() in ['language', 'lang']:
                            track['language'] = value.lower()
                            break
                    
                    # Если язык не найден, пробуем другие поля
                    if track['language'] == 'unknown':
                        title = tags.get('title', '').lower()
                        if 'english' in title or 'eng' in title:
                            track['language'] = 'eng'
                        elif 'russian' in title or 'rus' in title:
                            track['language'] = 'rus'
                    
                    file_info['audio_tracks'].append(track)
            
            return file_info
            
        except Exception as e:
            logger.error(f"Ошибка анализа файла {file_path.name}: {e}")
            return self._get_basic_file_info(file_path)
    
    def _get_basic_file_info(self, file_path: Path) -> Dict:
        """Получение базовой информации о файле без ffprobe"""
        return {
            'name': file_path.name,
            'size': file_path.stat().st_size,
            'audio_tracks': [
                {'channels': 6, 'language': 'unknown', 'codec': 'unknown'}
            ]
        }

    async def send_startup_notification(self, watch_dir: Path, check_interval: int):
        """Отправка визуального уведомления о запуске с информацией о директории"""
        try:
            # Сканируем директорию для получения актуальной информации
            all_files = []
            extensions = self.config.get('FileTypes', 'extensions', '.mp4,.mkv').split(',')
            min_size_mb = self.config.getint('Advanced', 'min_file_size_mb', 100)
            min_size_bytes = min_size_mb * 1024 * 1024
            
            def scan_for_startup(path: Path, depth: int = 0):
                max_depth = self.config.getint('General', 'max_depth', 2)
                if depth > max_depth:
                    return
                
                try:
                    for item in path.iterdir():
                        if item.is_dir():
                            scan_for_startup(item, depth + 1)
                        elif item.is_file():
                            if (item.suffix.lower() in extensions and 
                                item.stat().st_size >= min_size_bytes):
                                
                                # Определяем статус файла
                                if str(item) in self.processed_files:
                                    status = 'processed'
                                else:
                                    status = 'pending'
                                
                                all_files.append({
                                    'name': item.name,
                                    'status': status,
                                    'size': item.stat().st_size
                                })
                except (PermissionError, OSError):
                    pass
            
            scan_for_startup(watch_dir)
            
            # Подсчитываем статистику
            processed_count = len([f for f in all_files if f['status'] == 'processed'])
            pending_count = len([f for f in all_files if f['status'] == 'pending'])
            
            # Подготавливаем данные для визуальной карточки
            startup_info = {
                'stats': {
                    'total_files': len(all_files),
                    'processed_files': processed_count,
                    'pending_files': pending_count,
                    'error_files': self.stats.get('errors', 0)
                },
                'recent_files': all_files[:8],  # Показываем первые 8 файлов
                'directory': str(watch_dir),
                'interval': check_interval,
                'startup': True
            }
            
            # Отправляем визуальную карточку
            message = f"🚀 Мониторинг запущен\n📁 {watch_dir}\n⏱ Интервал: {check_interval}с"
            await self.notifier.send_directory_summary_notification(startup_info, message)
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления о запуске: {e}")
            # Fallback к простому текстовому сообщению
            message = f"🚀 <b>Мониторинг запущен</b>\n\n📁 Директория: {watch_dir}\n⏱ Интервал: {check_interval}с"
            await self.notifier.send_message(message)

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

        # Отправляем визуальное уведомление о запуске с состоянием директории
        if self.notifier and self.config.getboolean('Telegram', 'notify_on_start'):
            await self.send_startup_notification(watch_dir, check_interval)

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
        """Отправка визуальной сводки в Telegram"""
        if not self.notifier:
            return

        # Подготавливаем данные для визуальной сводки
        summary_info = {
            'stats': {
                'total_files': self.stats['total_processed'],
                'processed_files': self.stats['converted'],
                'pending_files': 0,  # В текущей реализации мы не отслеживаем ожидающие файлы
                'error_files': self.stats['errors']
            },
            'recent_files': []  # Можно добавить последние обработанные файлы
        }

        # Отправляем визуальную сводку
        await self.notifier.send_directory_summary_notification(summary_info)
        
        # Очищаем временные файлы
        self.notifier.cleanup_temp_files()

    def stop(self):
        """Остановка мониторинга"""
        logger.info("Останавливаем мониторинг...")
        self.running = False