#!/usr/bin/env python3
"""
Basic State Management Tests
Базовые тесты системы управления состояниями
"""

import asyncio
import os
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import sqlite3
import json
import pytest

# Импортируем компоненты системы
from ..store import StateStore
from ..machine import AudioStateMachine, create_state_machine
from ..config import StateConfig, get_development_config
from ..metrics import get_metrics, init_metrics
from ..models import FileEntry
from ..enums import IntegrityStatus, ProcessedStatus


@pytest.mark.asyncio
async def test_basic_lifecycle():
    """Базовый тест жизненного цикла файла"""
    print("TEST 1: Базовый жизненный цикл файла")
    
    # Создаем временную директорию и БД
    temp_dir = Path(tempfile.mkdtemp(prefix="state_test_"))
    test_db = temp_dir / "test_state.db"
    
    try:
        # Создаем конфигурацию
        config = get_development_config()
        config.storage_url = str(test_db)
        config.stable_wait_sec = 1  # быстрее для тестов
        
        # Создаем state machine
        machine = create_state_machine(str(test_db), config.to_dict())
        
        # Создаем тестовый файл
        test_file = temp_dir / "movie.mp4"
        with open(test_file, 'wb') as f:
            f.write(b'0' * (1024 * 1024))  # 1MB
        
        print(f"   Создан тестовый файл: {test_file}")
        
        # Обнаруживаем файл
        entry = await machine.process_file(test_file)
        print(f"   Файл обнаружен: ID={entry.id}, статус={entry.processed_status.value}")
        print(f"   Stable_since: {entry.stable_since}")
        
        # Файл не должен быть стабильным сразу
        assert entry.stable_since is None, "Новый файл не должен быть стабильным"
        
        # Ждем стабилизации
        print("   Ожидание стабилизации...")
        await asyncio.sleep(1.5)
        
        # Повторно обрабатываем
        processed = await machine.process_pending_files(limit=1)
        print(f"   Обработано файлов: {processed}")
        
        # Проверяем финальное состояние
        final_entry = machine.store.get_file(test_file)
        if final_entry:
            print(f"   Финальный статус: integrity={final_entry.integrity_status.value}")
            print(f"   Processed: {final_entry.processed_status.value}")
        
        machine.stop()
        print("   OK: Базовый тест завершен успешно")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        return False
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_size_change_reset():
    """Тест сброса цикла при изменении размера"""
    print("\nTEST 2: Сброс цикла при изменении размера")
    
    temp_dir = Path(tempfile.mkdtemp(prefix="state_test_"))
    test_db = temp_dir / "test_state.db"
    
    try:
        config = get_development_config()
        config.storage_url = str(test_db)
        config.stable_wait_sec = 1
        
        machine = create_state_machine(str(test_db), config.to_dict())
        
        # Создаем файл
        test_file = temp_dir / "movie.mp4"
        with open(test_file, 'wb') as f:
            f.write(b'0' * (2 * 1024 * 1024))  # 2MB
        
        # Первый цикл обработки
        entry1 = await machine.process_file(test_file)
        await asyncio.sleep(1.5)  # ждем стабилизации
        await machine.process_pending_files(limit=1)
        
        # Сохраняем состояние
        entry_before = machine.store.get_file(test_file)
        old_status = entry_before.integrity_status if entry_before else IntegrityStatus.UNKNOWN
        
        print(f"   До изменения: integrity={old_status.value}")
        
        # Изменяем размер файла
        with open(test_file, 'wb') as f:
            f.write(b'0' * (3 * 1024 * 1024))  # 3MB
        
        # Обновляем время изменения
        os.utime(test_file, (time.time(), time.time()))
        
        # Повторно обрабатываем
        entry_after = await machine.process_file(test_file)
        
        print(f"   После изменения: integrity={entry_after.integrity_status.value}")
        print(f"   Processed: {entry_after.processed_status.value}")
        print(f"   Stable_since сброшен: {entry_after.stable_since is None}")
        
        # Проверяем сброс
        assert entry_after.integrity_status == IntegrityStatus.UNKNOWN, "Integrity должен сброситься"
        assert entry_after.processed_status == ProcessedStatus.NEW, "Processed должен сброситься"
        assert entry_after.stable_since is None, "stable_since должен сброситься"
        
        machine.stop()
        print("   OK: Тест сброса прошел успешно")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        return False
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


async def run_basic_tests():
    """Запуск базовых тестов"""
    print("=== БАЗОВОЕ ТЕСТИРОВАНИЕ ===")
    
    # Инициализируем метрики
    init_metrics(retention_hours=1, max_events=1000)
    
    tests = [
        ("Базовый жизненный цикл", test_basic_lifecycle),
        ("Сброс при изменении размера", test_size_change_reset)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                passed += 1
                print(f"   -> PASSED\n")
            else:
                failed += 1
                print(f"   -> FAILED\n")
                
        except Exception as e:
            failed += 1
            print(f"   -> ERROR: {e}\n")
    
    print("=== РЕЗУЛЬТАТ ===")
    print(f"Тестов пройдено: {passed}")
    print(f"Тестов не прошло: {failed}")
    
    return failed == 0


if __name__ == "__main__":
    asyncio.run(run_basic_tests())