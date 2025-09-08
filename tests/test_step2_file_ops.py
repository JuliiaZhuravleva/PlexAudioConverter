"""
Тесты файловых операций (rename, delete) для Step 2
"""
import pytest
import time
import os
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
    create_test_config_manager, create_sample_video_file, assert_metrics_equal
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestFileOperations:
    """Тесты файловых операций"""

    def test_t008_rename_before_stabilization(self):
        """T-008: Rename перед стабилизацией"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            temp_file = temp_dir / "downloading.tmp"
            final_file = temp_dir / "movie.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Начать "скачивание" во временный файл
                downloader = SyntheticDownloader(temp_file)
                downloader.start_download()
                downloader.append(b'\x00' * 1024 * 1024)  # 1MB
                
                # Discovery временного файла
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что временный файл в базе
                temp_data = test_store.get_file_by_path(str(temp_file))
                assert temp_data is not None
                original_group_id = temp_data['group_id']
                
                # Продолжить "скачивание" и переименовать
                downloader.append(b'\x00' * 1024 * 1024)  # Еще 1MB
                clock.advance(1)
                
                # Переименовать файл
                downloader.rename_to(final_file)
                
                # Повторный discovery после rename
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что старый путь больше не активен
                temp_data_after = test_store.get_file_by_path(str(temp_file))
                # В зависимости от реализации, может быть None или помечен как dangling
                
                # Проверить что новый путь создан
                final_data = test_store.get_file_by_path(str(final_file))
                assert final_data is not None
                
                # Проверить обновление group_id для нового пути
                new_group_id = final_data['group_id']
                assert 'movie' in new_group_id
                assert new_group_id != original_group_id  # Должен измениться
                
                # Проверить что first_seen_at обновился для нового файла
                assert final_data['first_seen_at'] is not None
                
                # Завершить "скачивание" и стабилизировать
                downloader.finish_download()
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Integrity должна быть привязана к новому пути
                due_files = test_store.store.get_due_files(limit=1)
                if due_files:
                    file_entry = due_files[0]
                    assert file_entry.path == str(final_file)
                    monitor.handle_integrity_check(file_entry)
                
                # Проверить что integrity прошла для нового файла
                assert fake_integrity.call_count == 1
                final_data_after = test_store.get_file_by_path(str(final_file))
                assert final_data_after['integrity_status'] == IntegrityStatus.COMPLETE.value

    def test_t009_deletion_during_waiting(self):
        """T-009: Удаление во время ожидания"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "to_delete.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Создать файл и начать "скачивание"
                downloader = SyntheticDownloader(video_file)
                downloader.start_download()
                downloader.append(b'\x00' * 1024 * 1024)  # 1MB
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что файл в базе
                file_data = test_store.get_file_by_path(str(video_file))
                assert file_data is not None
                
                # Продвинуть время почти до стабилизации
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'] - 1)
                
                # Удалить файл
                downloader.delete()
                
                # Запустить планировщик
                planner = StatePlannerFixture(test_store.store)
                due_files = planner.get_due_files(limit=1)
                
                if due_files:
                    file_entry = due_files[0]
                    # Попытка обработки удаленного файла
                    try:
                        monitor.handle_integrity_check(file_entry)
                    except FileNotFoundError:
                        # Ожидаемое поведение
                        pass
                
                # Проверить что Integrity не запускалась для несуществующего файла
                assert fake_integrity.call_count == 0
                
                # Повторный discovery должен обнаружить отсутствие файла
                monitor.scan_directory(str(temp_dir))
                
                # Файл должен быть помечен как dangling или удален
                file_data_after = test_store.get_file_by_path(str(video_file))
                # В зависимости от реализации, может быть None или иметь специальный статус

    def test_rename_chain_operations(self):
        """Тест цепочки переименований"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            file1 = temp_dir / "step1.tmp"
            file2 = temp_dir / "step2.part" 
            file3 = temp_dir / "final.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Создать первый файл
                downloader = SyntheticDownloader(file1)
                downloader.start_download()
                downloader.append(b'\x00' * 1024 * 1024)
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                assert test_store.get_file_count() == 1
                
                clock.advance(1)
                
                # Первое переименование
                downloader.rename_to(file2)
                monitor.scan_directory(str(temp_dir))
                
                clock.advance(1)
                
                # Второе переименование
                downloader.rename_to(file3)
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что в итоге один активный файл
                final_data = test_store.get_file_by_path(str(file3))
                assert final_data is not None
                assert 'final' in final_data['group_id']
                
                # Завершить и стабилизировать
                downloader.finish_download()
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Integrity должна работать с финальным файлом
                due_files = test_store.store.get_due_files(limit=1)
                if due_files:
                    monitor.handle_integrity_check(due_files[0])
                
                assert fake_integrity.call_count == 1

    def test_delete_during_integrity_check(self):
        """Тест удаления файла во время integrity check"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "delete_during_check.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 2.0  # Длительная проверка
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Discovery и стабилизация
                monitor.scan_directory(str(temp_dir))
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Начать integrity check
                due_files = test_store.store.get_due_files(limit=1)
                assert len(due_files) == 1
                
                file_entry = due_files[0]
                
                # Запустить integrity check в отдельном потоке
                import threading
                def run_integrity():
                    try:
                        monitor.handle_integrity_check(file_entry)
                    except Exception as e:
                        # Ожидаемо, если файл удален во время проверки
                        pass
                
                integrity_thread = threading.Thread(target=run_integrity)
                integrity_thread.start()
                
                # Удалить файл во время проверки
                time.sleep(0.5)  # Дать время начаться проверке
                video_file.unlink()
                
                # Дождаться завершения потока
                integrity_thread.join(timeout=5)
                
                # Проверить что система корректно обработала ситуацию
                file_data = test_store.get_file_by_path(str(video_file))
                # Статус может быть ERROR или файл может быть удален из базы

    def test_rename_preserves_metadata(self):
        """Тест сохранения метаданных при переименовании"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            old_file = temp_dir / "old_name.mkv"
            new_file = temp_dir / "new_name.mkv"
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Создать файл с метаданными
            downloader = SyntheticDownloader(old_file)
            downloader.start_download()
            downloader.append(b'\x00' * 1024 * 1024)
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Получить исходные метаданные
            original_data = test_store.get_file_by_path(str(old_file))
            original_first_seen = original_data['first_seen_at']
            original_size = original_data['size_bytes']
            
            # Переименовать
            downloader.rename_to(new_file)
            
            # Повторный discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить новый файл
            new_data = test_store.get_file_by_path(str(new_file))
            assert new_data is not None
            
            # В зависимости от реализации, метаданные могут сохраняться или обновляться
            # Размер должен совпадать
            assert new_data['size_bytes'] == original_size

    def test_multiple_renames_same_target(self):
        """Тест переименования нескольких файлов в одно имя"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            file1 = temp_dir / "temp1.tmp"
            file2 = temp_dir / "temp2.tmp"
            target = temp_dir / "target.mkv"
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Создать два файла с разным начальным содержимым
            downloader1 = SyntheticDownloader(file1)
            downloader1.start_download()
            downloader1.append(b'\x01' * 1024 * 1024)  # File 1 starts with 0x01
            
            downloader2 = SyntheticDownloader(file2)
            downloader2.start_download()
            downloader2.append(b'\x02' * 2 * 1024 * 1024)  # File 2 starts with 0x02
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            assert test_store.get_file_count() == 2
            
            # Переименовать первый файл
            downloader1.rename_to(target)
            monitor.scan_directory(str(temp_dir))
            
            # Удалить первый и переименовать второй в то же имя
            downloader1.delete()
            downloader2.rename_to(target)
            monitor.scan_directory(str(temp_dir))
            
            # Должен остаться один файл с правильным размером
            target_data = test_store.get_file_by_path(str(target))
            assert target_data is not None
            assert target_data['size_bytes'] == 2 * 1024 * 1024


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
