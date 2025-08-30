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