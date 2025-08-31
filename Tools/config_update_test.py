#!/usr/bin/env python3
"""
Config Update Test Tool

Тестирует автоматическое обновление конфигурации при добавлении новых секций и опций.
"""

import os
import sys
import shutil
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config_manager import ConfigManager
from core.logger import logger


def test_config_auto_update():
    """Тестирование автоматического обновления конфигурации"""
    
    print("🧪 Тестирование автоматического обновления конфигурации")
    print("=" * 60)
    
    # Создаем тестовую директорию
    test_dir = Path("/temp/config_test")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Путь к тестовому конфигу
    test_config_path = test_dir / "test_config.ini"
    
    try:
        # Шаг 1: Создаем старый конфиг без секции [Download]
        old_config_content = """[General]
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
        
        print("📝 Создаем старый конфиг без секции [Download]...")
        with open(test_config_path, 'w', encoding='utf-8') as f:
            f.write(old_config_content.strip())
        
        # Шаг 2: Загружаем конфиг через ConfigManager
        print("🔄 Загружаем конфиг через ConfigManager...")
        config_manager = ConfigManager(str(test_config_path))
        
        # Шаг 3: Проверяем, что новые опции доступны
        print("✅ Проверяем доступность новых опций...")
        
        # Проверяем секцию Download
        download_enabled = config_manager.getboolean('Download', 'enabled', False)
        check_interval = config_manager.getfloat('Download', 'check_interval', 0.0)
        stability_threshold = config_manager.getfloat('Download', 'stability_threshold', 0.0)
        notify_on_complete = config_manager.getboolean('Download', 'notify_on_complete', False)
        cleanup_hours = config_manager.getint('Download', 'cleanup_completed_hours', 0)
        
        print(f"   Download.enabled: {download_enabled}")
        print(f"   Download.check_interval: {check_interval}")
        print(f"   Download.stability_threshold: {stability_threshold}")
        print(f"   Download.notify_on_complete: {notify_on_complete}")
        print(f"   Download.cleanup_completed_hours: {cleanup_hours}")
        
        # Шаг 4: Проверяем содержимое обновленного файла
        print("\n📄 Проверяем содержимое обновленного файла...")
        with open(test_config_path, 'r', encoding='utf-8') as f:
            updated_content = f.read()
        
        if '[Download]' in updated_content:
            print("✅ Секция [Download] успешно добавлена!")
        else:
            print("❌ Секция [Download] НЕ найдена!")
            return False
            
        if 'stability_threshold' in updated_content:
            print("✅ Опция stability_threshold найдена!")
        else:
            print("❌ Опция stability_threshold НЕ найдена!")
            return False
        
        # Шаг 5: Тестируем добавление отдельной опции
        print("\n🔧 Тестируем добавление отдельной опции...")
        
        # Удаляем одну опцию из существующей секции
        modified_content = updated_content.replace('notify_on_complete = true', '')
        with open(test_config_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        # Перезагружаем конфиг
        config_manager2 = ConfigManager(str(test_config_path))
        
        # Проверяем, что опция восстановлена
        notify_restored = config_manager2.getboolean('Download', 'notify_on_complete', False)
        print(f"   Восстановленная опция notify_on_complete: {notify_restored}")
        
        if notify_restored:
            print("✅ Отдельная опция успешно восстановлена!")
        else:
            print("❌ Отдельная опция НЕ восстановлена!")
            return False
        
        print("\n🎉 Все тесты пройдены успешно!")
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка тестирования: {e}")
        logger.error(f"Ошибка в тесте обновления конфигурации: {e}")
        return False
        
    finally:
        # Очистка
        try:
            if test_dir.exists():
                shutil.rmtree(test_dir)
                print(f"\n🧹 Очищена тестовая директория: {test_dir}")
        except Exception as e:
            print(f"⚠️ Ошибка очистки: {e}")


if __name__ == '__main__':
    success = test_config_auto_update()
    if success:
        print("\n✅ Тестирование завершено успешно!")
        sys.exit(0)
    else:
        print("\n❌ Тестирование завершено с ошибками!")
        sys.exit(1)
