#!/usr/bin/env python3
"""
Performance Tests
Тесты производительности системы управления состояниями
"""

import time
import tempfile
import shutil
from pathlib import Path
from ..store import StateStore
from ..models import FileEntry
from ..enums import IntegrityStatus, ProcessedStatus


def test_database_performance():
    """Нагрузочный тест БД"""
    print("PERFORMANCE TEST: База данных с 5000 записей")
    
    temp_dir = Path(tempfile.mkdtemp(prefix="perf_test_"))
    test_db = temp_dir / "perf.db"
    
    try:
        store = StateStore(test_db)
        current_time = int(time.time())
        
        # 1. Тест массового создания записей
        print("   Создание 5000 записей...")
        start_time = time.time()
        
        batch_size = 100
        for batch in range(50):  # 50 * 100 = 5000
            for i in range(batch_size):
                file_id = batch * batch_size + i
                entry = FileEntry(
                    id=None,
                    path=f"/test/batch_{batch}/movie_{i:04d}.mp4",
                    group_id=f"group_{file_id:04d}",
                    is_stereo=(i % 3 == 0),  # каждый третий stereo
                    size_bytes=1024 * 1024 * (1 + i % 20),  # варьируем размер 1-20MB
                    mtime=current_time - (i % 1000),
                    first_seen_at=current_time,
                    stable_since=current_time if i % 2 == 0 else None,  # половина стабильна
                    next_check_at=current_time + (i % 600),  # разные времена
                    integrity_status=IntegrityStatus.UNKNOWN,
                    processed_status=ProcessedStatus.NEW,
                    updated_at=current_time
                )
                store.upsert_file(entry)
            
            if (batch + 1) % 10 == 0:
                elapsed = time.time() - start_time
                print(f"     {(batch + 1) * batch_size} записей за {elapsed:.2f}с")
        
        creation_time = time.time() - start_time
        records_per_sec = 5000 / creation_time
        print(f"   Создание завершено: {creation_time:.2f}с ({records_per_sec:.0f} записей/сек)")
        
        # 2. Тест производительности запросов
        print("   Тестирование производительности запросов...")
        
        # get_due_files (основной запрос планировщика)
        query_times = []
        for test_run in range(20):
            test_time = current_time + (test_run * 30)  # разные временные точки
            
            start = time.time()
            due_files = store.get_due_files(test_time, limit=100)
            elapsed = time.time() - start
            query_times.append(elapsed)
        
        avg_query_time = sum(query_times) / len(query_times)
        max_query_time = max(query_times)
        min_query_time = min(query_times)
        
        print(f"   get_due_files(limit=100): среднее {avg_query_time*1000:.2f}мс, макс {max_query_time*1000:.2f}мс")
        
        # Тест get_files_by_group
        group_times = []
        for i in range(10):
            group_id = f"group_{i:04d}"
            start = time.time()
            group_files = store.get_files_by_group(group_id)
            elapsed = time.time() - start
            group_times.append(elapsed)
        
        avg_group_time = sum(group_times) / len(group_times)
        print(f"   get_files_by_group: среднее {avg_group_time*1000:.2f}мс")
        
        # 3. Тест статистики
        start = time.time()
        stats = store.get_stats()
        stats_time = time.time() - start
        
        print(f"   Статистика за {stats_time*1000:.2f}мс:")
        print(f"     Файлов: {stats['total_files']}")
        print(f"     Групп: {stats['total_groups']}")  
        print(f"     Готовых к проверке: {stats['due_files']}")
        
        # 4. Тест обновления записей
        print("   Тест массового обновления...")
        
        update_start = time.time()
        
        # Обновляем каждый 10-й файл
        for i in range(0, 5000, 10):
            file_path = f"/test/batch_{i//100}/movie_{i%100:04d}.mp4"
            entry = store.get_file(file_path)
            if entry:
                entry.size_bytes += 1024  # увеличиваем размер
                entry.updated_at = current_time + 1
                store.upsert_file(entry)
        
        update_time = time.time() - update_start
        updates_per_sec = 500 / update_time  # обновили 500 записей
        print(f"   500 обновлений за {update_time:.2f}с ({updates_per_sec:.0f} обновлений/сек)")
        
        # 5. Проверка критериев производительности
        print("\n   === ПРОВЕРКА ПРОИЗВОДИТЕЛЬНОСТИ ===")
        
        performance_ok = True
        
        # Запросы должны быть быстрыми (< 50мс)
        if avg_query_time > 0.05:
            print(f"   WARNING: get_due_files медленный: {avg_query_time*1000:.2f}мс")
            performance_ok = False
        else:
            print(f"   OK: get_due_files быстрый: {avg_query_time*1000:.2f}мс")
        
        # Создание записей должно быть разумной скорости (> 100 записей/сек)
        if records_per_sec < 100:
            print(f"   WARNING: Создание записей медленное: {records_per_sec:.0f} записей/сек")
            performance_ok = False
        else:
            print(f"   OK: Создание записей: {records_per_sec:.0f} записей/сек")
        
        # Статистика должна быть быстрой (< 100мс)
        if stats_time > 0.1:
            print(f"   WARNING: Статистика медленная: {stats_time*1000:.2f}мс") 
            performance_ok = False
        else:
            print(f"   OK: Статистика быстрая: {stats_time*1000:.2f}мс")
        
        if performance_ok:
            print("   RESULT: Производительность отличная!")
        else:
            print("   RESULT: Есть проблемы с производительностью")
        
        return performance_ok
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def test_store_operations():
    """Тест операций store"""
    print("\nSTORE TEST: Основные операции хранилища")
    
    temp_dir = Path(tempfile.mkdtemp(prefix="store_test_"))
    test_db = temp_dir / "store.db"
    
    try:
        store = StateStore(test_db)
        current_time = int(time.time())
        
        # Создаем тестовую запись
        entry = FileEntry(
            id=None,
            path="/test/movie.mp4",
            group_id="test_group",
            is_stereo=False,
            size_bytes=1024*1024,
            mtime=current_time,
            first_seen_at=current_time,
            stable_since=None,
            next_check_at=current_time,
            integrity_status=IntegrityStatus.UNKNOWN,
            processed_status=ProcessedStatus.NEW,
            updated_at=current_time
        )
        
        # Тест upsert
        saved_entry = store.upsert_file(entry)
        print(f"   Создана запись с ID: {saved_entry.id}")
        
        # Тест get
        retrieved = store.get_file("/test/movie.mp4")
        assert retrieved is not None, "Запись не найдена"
        assert retrieved.id == saved_entry.id, "ID не совпадают"
        print(f"   Запись получена: ID={retrieved.id}")
        
        # Тест update
        retrieved.size_bytes = 2 * 1024 * 1024
        updated = store.upsert_file(retrieved)
        print(f"   Запись обновлена: размер={updated.size_bytes}")
        
        # Тест get_due_files
        due_files = store.get_due_files(current_time + 1, limit=10)
        print(f"   Готовых файлов: {len(due_files)}")
        
        # Тест статистики
        stats = store.get_stats()
        print(f"   Статистика: {stats['total_files']} файлов")
        
        print("   OK: Операции Store работают")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def run_performance_tests():
    """Запуск тестов производительности"""
    print("=== ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ ===")
    
    tests = [
        ("Операции Store", test_store_operations),
        ("Производительность БД", test_database_performance)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"   -> PASSED\n")
            else:
                failed += 1
                print(f"   -> FAILED\n")
                
        except Exception as e:
            failed += 1
            print(f"   -> ERROR: {e}\n")
            import traceback
            traceback.print_exc()
    
    print("=== РЕЗУЛЬТАТ ===")
    print(f"Прошло: {passed}, Не прошло: {failed}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_performance_tests()
    exit(0 if success else 1)