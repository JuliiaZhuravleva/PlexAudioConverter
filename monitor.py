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
from pathlib import Path
from typing import Dict, List, Optional
import signal
from core.config_manager import ConfigManager
from core.audio_monitor import AudioMonitor
from core.logger import logger

# Для Windows службы
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    WINDOWS_SERVICE = True
except ImportError:
    WINDOWS_SERVICE = False


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
