#!/usr/bin/env python3
"""
Plex Audio Converter - Core Modules
Ядро системы для автоматической конвертации многоканального аудио
"""

# Основные модули
from .logger import logger
from .config_manager import ConfigManager
from .telegram_notifier import TelegramNotifier
from .audio_monitor import AudioMonitor
from .windows_service import AudioMonitorService

__version__ = "1.5.0"
__author__ = "Assistant"

__all__ = [
    'logger',
    'ConfigManager',
    'TelegramNotifier',
    'AudioMonitor',
    'AudioMonitorService'
]