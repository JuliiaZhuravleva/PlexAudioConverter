import configparser
from pathlib import Path
from .logger import logger


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

[Download]
# Включить мониторинг загрузок
enabled = true
# Интервал проверки загрузок в секундах
check_interval = 5.0
# Время стабильности файла для считания завершенным (секунды)
stability_threshold = 30.0
# Уведомления о завершении загрузки
notify_on_complete = true
# Автоочистка завершенных загрузок (часы)
cleanup_completed_hours = 24
"""

    def __init__(self, config_file: str = 'monitor_config.ini'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        """Загрузка конфигурации с автоматическим обновлением"""
        if not Path(self.config_file).exists():
            self.create_default_config()
        else:
            # Проверяем и обновляем существующий конфиг
            self._update_existing_config()

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

    def getfloat(self, section: str, option: str, fallback=0.0):
        """Получение значения с плавающей точкой"""
        try:
            return self.config.getfloat(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def _parse_default_config(self) -> configparser.ConfigParser:
        """Парсинг конфигурации по умолчанию"""
        default_config = configparser.ConfigParser()
        default_config.read_string(self.DEFAULT_CONFIG.strip())
        return default_config
    
    def _update_existing_config(self):
        """Обновление существующего конфига новыми секциями и опциями"""
        try:
            # Загружаем существующий конфиг
            existing_config = configparser.ConfigParser()
            existing_config.read(self.config_file, encoding='utf-8')
            
            # Загружаем конфиг по умолчанию
            default_config = self._parse_default_config()
            
            # Проверяем, нужно ли обновление
            needs_update = False
            
            # Проверяем отсутствующие секции
            for section_name in default_config.sections():
                if not existing_config.has_section(section_name):
                    logger.info(f"Добавляем новую секцию: [{section_name}]")
                    existing_config.add_section(section_name)
                    needs_update = True
                    
                    # Добавляем все опции из этой секции
                    for option, value in default_config.items(section_name):
                        existing_config.set(section_name, option, value)
                        logger.debug(f"Добавлена опция: {section_name}.{option} = {value}")
                else:
                    # Проверяем отсутствующие опции в существующей секции
                    for option, value in default_config.items(section_name):
                        if not existing_config.has_option(section_name, option):
                            logger.info(f"Добавляем новую опцию: {section_name}.{option}")
                            existing_config.set(section_name, option, value)
                            needs_update = True
            
            # Сохраняем обновленный конфиг если были изменения
            if needs_update:
                self._save_config_with_comments(existing_config)
                logger.info("Конфигурация автоматически обновлена новыми параметрами")
                
        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации: {e}")
            logger.info("Используем конфигурацию как есть")
    
    def _save_config_with_comments(self, config: configparser.ConfigParser):
        """Сохранение конфигурации с комментариями из DEFAULT_CONFIG"""
        try:
            # Создаем словарь комментариев из DEFAULT_CONFIG
            comments = self._extract_comments_from_default()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                for section_name in config.sections():
                    # Записываем комментарий секции если есть
                    if section_name in comments['sections']:
                        f.write(f"\n{comments['sections'][section_name]}\n")
                    
                    f.write(f"[{section_name}]\n")
                    
                    for option, value in config.items(section_name):
                        # Записываем комментарий опции если есть
                        option_key = f"{section_name}.{option}"
                        if option_key in comments['options']:
                            f.write(f"{comments['options'][option_key]}\n")
                        
                        f.write(f"{option} = {value}\n")
                    
                    f.write("\n")  # Пустая строка между секциями
                    
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации с комментариями: {e}")
            # Fallback к стандартному сохранению
            with open(self.config_file, 'w', encoding='utf-8') as f:
                config.write(f)
    
    def _extract_comments_from_default(self) -> dict:
        """Извлечение комментариев из DEFAULT_CONFIG"""
        comments = {
            'sections': {},
            'options': {}
        }
        
        lines = self.DEFAULT_CONFIG.strip().split('\n')
        current_section = None
        pending_comments = []
        
        for line in lines:
            line = line.strip()
            
            if line.startswith('#'):
                # Это комментарий
                pending_comments.append(line)
            elif line.startswith('[') and line.endswith(']'):
                # Это секция
                current_section = line[1:-1]
                if pending_comments:
                    comments['sections'][current_section] = '\n'.join(pending_comments)
                    pending_comments = []
            elif '=' in line and current_section:
                # Это опция
                option = line.split('=')[0].strip()
                option_key = f"{current_section}.{option}"
                if pending_comments:
                    comments['options'][option_key] = '\n'.join(pending_comments)
                    pending_comments = []
            elif not line:
                # Пустая строка - сбрасываем накопленные комментарии
                pending_comments = []
        
        return comments