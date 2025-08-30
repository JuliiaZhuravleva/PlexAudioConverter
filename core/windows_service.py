import asyncio
from .config_manager import ConfigManager
from .audio_monitor import AudioMonitor

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    WINDOWS_SERVICE = True
except ImportError:
    WINDOWS_SERVICE = False


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