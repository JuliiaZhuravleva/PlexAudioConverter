"""
Тесты надежности, GC и миграций
"""
import pytest
import time
import json
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
    create_sample_video_file, assert_metrics_equal
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestReliabilityAndMaintenance:
    """Тесты надежности и обслуживания"""

    def test_t401_gc_processed_history(self):
        """T-401: GC processed-истории"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            config = create_test_config(max_state_entries=5)  # Малый лимит для теста
            
            # Создать много обработанных файлов
            for i in range(10):
                file_path = temp_dir / f"processed_{i}.mkv"
                create_sample_video_file(file_path, size_mb=10)
                
                # Добавить как обработанный
                test_store.store.upsert_file(
                    path=str(file_path),
                    size_bytes=10*1024*1024,
                    mtime=time.time() - (i * 3600),  # Разные времена
                    integrity_status=IntegrityStatus.COMPLETE,
                    processed_status=ProcessedStatus.CONVERTED,
                    next_check_at=time.time() + 365*24*3600  # Далеко в будущем
                )
            
            # Проверить что все файлы в базе
            assert test_store.get_file_count() == 10
            
            # Запустить GC (когда будет реализован)
            # test_store.store.cleanup_old_entries()
            
            # TODO: Проверить что старые записи удалены
            # remaining_count = test_store.get_file_count()
            # assert remaining_count <= config.max_state_entries

    def test_t402_migrator_from_legacy_processed_files(self):
        """T-402: Migrator из старого processed_files"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать legacy processed_files.json
            legacy_data = {
                "processed_files": [
                    str(temp_dir / "legacy1.mkv"),
                    str(temp_dir / "legacy2.mkv"),
                    str(temp_dir / "legacy3.mkv")
                ]
            }
            
            legacy_file = temp_dir / "processed_files.json"
            legacy_file.write_text(json.dumps(legacy_data))
            
            # Создать физические файлы
            for filename in ["legacy1.mkv", "legacy2.mkv", "legacy3.mkv"]:
                create_sample_video_file(temp_dir / filename, size_mb=50)
            
            config = create_test_config()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.store
            )
            
            # Запустить миграцию (когда будет реализована)
            # monitor.migrate_legacy_data(str(legacy_file))
            
            # TODO: Проверить что legacy файлы импортированы
            # for filename in ["legacy1.mkv", "legacy2.mkv", "legacy3.mkv"]:
            #     file_data = test_store.get_file_by_path(str(temp_dir / filename))
            #     assert file_data is not None
            #     assert file_data['processed_status'] == ProcessedStatus.CONVERTED.value
            #     # next_check_at должен быть далеко в будущем (исключение из планировщика)

    def test_t403_dangling_cleanup(self):
        """T-403: Dangling-cleanup"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "will_be_deleted.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            config = create_test_config()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.store
            )
            
            # Discovery файла
            monitor.scan_directory(str(temp_dir))
            assert test_store.get_file_count() == 1
            
            # Удалить физический файл
            video_file.unlink()
            
            # Запустить scan-верификацию (когда будет реализована)
            # monitor.verify_file_presence()
            
            # TODO: Проверить что запись удалена или помечена как IGNORED
            # file_data = test_store.get_file_by_path(str(video_file))
            # assert file_data is None or file_data['processed_status'] == ProcessedStatus.IGNORED.value
            
            # TODO: Проверить что due-очередь пустая
            # test_store.assert_no_due_files()

    def test_database_integrity_after_operations(self):
        """Тест целостности базы данных после различных операций"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            config = create_test_config()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.store
            )
            
            # Создать файлы
            files = []
            for i in range(5):
                file_path = temp_dir / f"integrity_test_{i}.mkv"
                create_sample_video_file(file_path, size_mb=10)
                files.append(file_path)
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить индексы и ограничения
            with test_store.store._get_connection() as conn:
                # Проверить что нет дубликатов по path
                cursor = conn.execute(
                    "SELECT path, COUNT(*) as cnt FROM files GROUP BY path HAVING cnt > 1"
                )
                duplicates = cursor.fetchall()
                assert len(duplicates) == 0, f"Found duplicate paths: {duplicates}"
                
                # Проверить внешние ключи (если есть)
                cursor = conn.execute("PRAGMA foreign_key_check")
                fk_violations = cursor.fetchall()
                assert len(fk_violations) == 0, f"Foreign key violations: {fk_violations}"
                
                # Проверить что все group_id в files существуют в groups
                cursor = conn.execute("""
                    SELECT f.group_id FROM files f 
                    LEFT JOIN groups g ON f.group_id = g.group_id 
                    WHERE g.group_id IS NULL
                """)
                orphaned_groups = cursor.fetchall()
                assert len(orphaned_groups) == 0, f"Orphaned group_ids: {orphaned_groups}"

    def test_concurrent_database_access(self):
        """Тест конкурентного доступа к базе данных"""
        import threading
        import sqlite3
        
        with TempFS() as temp_dir:
            db_file = temp_dir / "concurrent_test.db"
            
            # Создать несколько подключений
            def worker(worker_id):
                try:
                    with StateStoreFixture(db_path=str(db_file)) as store:
                        for i in range(10):
                            file_path = f"/test/worker_{worker_id}_file_{i}.mkv"
                            store.store.upsert_file(
                                path=file_path,
                                size_bytes=1024*1024,
                                mtime=time.time(),
                                integrity_status=IntegrityStatus.UNKNOWN,
                                processed_status=ProcessedStatus.NEW
                            )
                            time.sleep(0.01)  # Небольшая пауза
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e):
                        pytest.fail(f"Database lock detected in worker {worker_id}")
                    raise
            
            # Запустить несколько потоков
            threads = []
            for i in range(3):
                thread = threading.Thread(target=worker, args=(i,))
                threads.append(thread)
                thread.start()
            
            # Дождаться завершения
            for thread in threads:
                thread.join(timeout=10)
                assert not thread.is_alive(), "Thread did not complete in time"
            
            # Проверить результат
            with StateStoreFixture(db_path=str(db_file)) as final_store:
                assert final_store.get_file_count() == 30  # 3 workers * 10 files


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
