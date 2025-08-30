import logging
import sys

def setup_logger(name: str = __name__, log_file: str = 'audio_monitor.log'):
    """Настройка логгера для модуля"""
    logger = logging.getLogger(name)
    
    # Избегаем дублирования handlers
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Форматтер
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Handler для файла
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Handler для консоли
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

# Глобальный логгер для всего проекта
logger = setup_logger('PlexAudioConverter')