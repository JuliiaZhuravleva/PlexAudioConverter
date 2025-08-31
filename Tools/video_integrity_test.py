#!/usr/bin/env python3
"""
Video Integrity Test Tool

Тестирует новую систему проверки целостности видеофайлов с помощью FFmpeg.
Позволяет проверить работу детекции неполных/поврежденных видеофайлов.
"""

import sys
import logging
from pathlib import Path

# Добавляем путь к модулям проекта
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.video_integrity_checker import VideoIntegrityChecker, VideoIntegrityStatus
from core.download_monitor import DownloadMonitor, FileDownloadInfo

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_video_integrity():
    """Тестирует проверку целостности видеофайлов"""
    
    print("=== Тест системы проверки целостности видеофайлов ===\n")
    
    # Создаем экземпляр проверки
    checker = VideoIntegrityChecker()
    
    # Тестовые файлы (замените на реальные пути)
    test_files = [
        Path("E:/Download/Movie/TWD (Season 07) LOST 1080/TWD.[S07E04].HD1080.DD5.1.LostFilm.[qqss44].mkv"),
        Path("E:/Download/Movie/test_incomplete.mkv"),  # Несуществующий файл для теста
        Path("E:/Download/Movie/test_small.mp4"),      # Несуществующий файл для теста
    ]
    
    for test_file in test_files:
        print(f"Проверка файла: {test_file.name}")
        print(f"Путь: {test_file}")
        print(f"Существует: {test_file.exists()}")
        
        if test_file.exists():
            print(f"Размер: {test_file.stat().st_size / (1024*1024):.1f} MB")
        
        # Быстрая проверка
        try:
            is_complete, reason = checker.is_video_complete(test_file)
            print(f"Быстрая проверка: {'✓ ЗАВЕРШЕН' if is_complete else '✗ НЕ ЗАВЕРШЕН'}")
            print(f"Причина: {reason}")
        except Exception as e:
            print(f"Ошибка быстрой проверки: {e}")
        
        # Полная проверка
        try:
            integrity_info = checker.check_video_integrity(test_file)
            print(f"Статус целостности: {integrity_info.status.value.upper()}")
            print(f"Метод детекции: {integrity_info.detection_method}")
            
            if integrity_info.duration:
                print(f"Длительность: {integrity_info.duration:.1f} сек")
            if integrity_info.readable_duration:
                print(f"Читаемая длительность: {integrity_info.readable_duration:.1f} сек")
            if integrity_info.error_message:
                print(f"Ошибка: {integrity_info.error_message}")
                
        except Exception as e:
            print(f"Ошибка полной проверки: {e}")
        
        print("-" * 60)


def test_download_monitor_integration():
    """Тестирует интеграцию с системой мониторинга загрузок"""
    
    print("\n=== Тест интеграции с мониторингом загрузок ===\n")
    
    # Создаем мониторинг загрузок
    monitor = DownloadMonitor()
    
    # Тестовый файл
    test_file = Path("E:/Download/Movie/TWD (Season 07) LOST 1080/TWD.[S07E04].HD1080.DD5.1.LostFilm.[qqss44].mkv")
    
    if test_file.exists():
        print(f"Добавляем файл в мониторинг: {test_file.name}")
        
        # Добавляем файл в мониторинг
        monitor.add_file(test_file)
        
        # Получаем информацию о файле
        file_info = monitor.get_file_info(test_file)
        if file_info:
            print(f"Статус файла: {file_info.status.value}")
            print(f"Метод детекции: {file_info.detection_method}")
            print(f"Размер: {file_info.current_size / (1024*1024):.1f} MB")
            print(f"Стабильность: {file_info.stable_duration:.1f} сек")
        else:
            print("Не удалось получить информацию о файле")
    else:
        print(f"Тестовый файл не найден: {test_file}")
        print("Создайте тестовый файл или измените путь в коде")


def main():
    """Главная функция тестирования"""
    
    print("Проверка доступности FFmpeg...")
    
    # Проверяем доступность FFmpeg
    import subprocess
    try:
        result = subprocess.run(['ffprobe', '-version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✓ FFprobe доступен")
        else:
            print("✗ FFprobe недоступен")
            return
    except Exception as e:
        print(f"✗ Ошибка проверки FFprobe: {e}")
        print("Убедитесь, что FFmpeg установлен и доступен в PATH")
        return
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✓ FFmpeg доступен\n")
        else:
            print("✗ FFmpeg недоступен\n")
    except Exception as e:
        print(f"✗ Ошибка проверки FFmpeg: {e}\n")
    
    # Запускаем тесты
    test_video_integrity()
    test_download_monitor_integration()
    
    print("\n=== Тестирование завершено ===")


if __name__ == "__main__":
    main()
