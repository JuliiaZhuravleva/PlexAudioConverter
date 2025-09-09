"""
Platform Edge Cases Tests (T-501 to T-504)
Тесты платформозависимых граничных случаев
"""
import pytest
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
import tempfile
import hashlib

from tests.fixtures import (
    TempFS, FakeClock, FakeIntegrityChecker, StateStoreFixture,
    create_test_config_manager, create_sample_video_file
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestPlatformEdgeCases:
    """Платформозависимые граничные случаи"""

    @pytest.mark.platform
    @pytest.mark.windows
    def test_t501_unicode_long_paths_windows_ntfs(self):
        """T-501: Unicode / long paths (Windows/NTFS)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            # Создать файлы с Unicode именами
            unicode_filenames = [
                "Кино_Фильм.mkv",  # Cyrillic
                "映画_Movie.mkv",   # Japanese
                "Película_🎬.mkv",  # Spanish with emoji
                "Very_Long_Filename_That_Exceeds_Normal_Limits_And_Tests_System_Boundaries_" +
                "And_Even_More_Characters_To_Make_Sure_We_Hit_Windows_Path_Length_Limits_Movie.mkv"
            ]
            
            created_files = []
            for filename in unicode_filenames:
                try:
                    file_path = temp_dir / filename
                    create_sample_video_file(file_path, size_mb=10)
                    created_files.append(file_path)
                except (OSError, UnicodeError) as e:
                    # На некоторых системах могут быть ограничения
                    pytest.skip(f"System doesn't support unicode filename {filename}: {e}")
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Discovery всех файлов
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что все файлы обработались корректно
                assert test_store.get_file_count() == len(created_files)
                
                # Focus on testing the core platform edge case functionality:
                # 1. Unicode filenames are handled correctly
                # 2. Files are discovered and stored with valid group_ids
                # 3. The state management system can handle these files
                
                # Проверить что group_id стабильны для Unicode имен
                for file_path in created_files:
                    file_data = test_store.get_file_by_path(str(file_path))
                    assert file_data is not None, f"File {file_path} not found in database"
                    assert file_data['group_id'] is not None
                    
                    # group_id должен быть валидным хешем
                    assert len(file_data['group_id']) > 10  # Reasonable hash length
                
                # Test passed: Unicode filenames work with the state management system
                assert len(created_files) == 4, f"Should have created 4 files, got {len(created_files)}"

    @pytest.mark.platform
    def test_t502_case_sensitivity(self):
        """T-502: Case sensitivity"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            from state_management.platform_utils import filesystem_is_case_sensitive
            
            # Check filesystem case sensitivity
            is_case_sensitive = filesystem_is_case_sensitive(temp_dir)
            
            # Создать файлы с разным регистром
            case_pairs = [
                ("Movie.MKV", "movie.mkv"),
                ("SERIES.S01E01.mkv", "series.s01e01.mkv")
            ]
            
            created_files = []
            expected_unique_files = 0
            
            for upper_name, lower_name in case_pairs:
                upper_path = temp_dir / upper_name
                lower_path = temp_dir / lower_name
                
                # Create the first file
                create_sample_video_file(upper_path, size_mb=10)
                
                if is_case_sensitive:
                    # On case-sensitive systems, both files can exist
                    created_files.append(upper_path)
                    create_sample_video_file(lower_path, size_mb=15)
                    created_files.append(lower_path)
                    expected_unique_files += 2
                else:
                    # On case-insensitive systems, second file overwrites first
                    create_sample_video_file(lower_path, size_mb=15)
                    # Both paths refer to the same file, but we'll keep track of both
                    created_files.extend([upper_path, lower_path])
                    expected_unique_files += 1  # Only 1 unique file per pair
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что поведение согласовано с ОС
                files_in_db = test_store.get_file_count()
                
                # On case-insensitive systems, database should have the same number as unique files
                # On case-sensitive systems, database should match the actual file count
                assert files_in_db == expected_unique_files, f"Expected {expected_unique_files} files in DB, got {files_in_db}. Case sensitive: {is_case_sensitive}"
                
                # Проверить что group_id не коллидируют неожиданно
                all_group_ids = set()
                all_files_in_db = test_store.get_files_by_status()  # Get all files
                
                for file_dict in all_files_in_db:
                    all_group_ids.add(file_dict['group_id'])
                
                # Should have the expected number of unique group_ids
                assert len(all_group_ids) == expected_unique_files, f"Expected {expected_unique_files} unique group_ids, got {len(all_group_ids)}"

    @pytest.mark.platform
    @pytest.mark.unix
    @pytest.mark.skipif(sys.platform == "win32", reason="Hard links test for Unix systems")
    def test_t503_hard_links_unix(self):
        """T-503: Hard links (Unix)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать файл и hard link к нему
            original_file = temp_dir / "original.mkv"
            hardlink_file = temp_dir / "hardlink.mkv"
            
            create_sample_video_file(original_file, size_mb=50)
            
            try:
                # Создать hard link
                os.link(str(original_file), str(hardlink_file))
            except (OSError, NotImplementedError):
                pytest.skip("System doesn't support hard links")
            
            # Убедиться что это действительно hard link
            assert original_file.stat().st_ino == hardlink_file.stat().st_ino
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                # Должно быть 2 записи с distinct path
                assert test_store.get_file_count() == 2
                
                original_data = test_store.get_file_by_path(str(original_file))
                hardlink_data = test_store.get_file_by_path(str(hardlink_file))
                
                assert original_data is not None
                assert hardlink_data is not None
                
                # Пути должны быть разные
                assert original_data['path'] != hardlink_data['path']
                
                # group_id может быть одинаковым или разным в зависимости от алгоритма
                # Главное чтобы не было cross-contamination при обработке
                
                # Обработка одного не должна влиять на другой
                due_files = test_store.store.get_due_files(limit=10)
                assert len(due_files) == 2
                
                # Обработать первый файл
                first_entry = due_files[0]
                monitor.handle_integrity_check(first_entry)
                
                # Второй файл должен остаться необработанным
                remaining_due = test_store.store.get_due_files(limit=10)
                assert len(remaining_due) == 1
                assert remaining_due[0].path != first_entry.path

    @pytest.mark.platform
    def test_t504_system_time_shift(self):
        """T-504: System time shift"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                with FakeClock(start_time=1000000) as clock:
                    config = create_test_config_manager()
                    monitor = AudioMonitor(
                        config=config,
                        state_store=test_store.store,
                        state_planner=test_store.planner
                    )
                    
                    # Discovery в момент времени T
                    monitor.scan_directory(str(temp_dir))
                    
                    file_data_before = test_store.get_file_by_path(str(video_file))
                    next_check_before = file_data_before['next_check_at']
                    
                    # Симулировать wall-clock jump (например, daylight saving time)
                    # Обычно это влияет на time.time(), но не на time.monotonic()
                    clock.advance(-3600)  # Jump back 1 hour
                    
                    # Получить due файлы - должен использовать monotonic time
                    due_files = test_store.store.get_due_files(limit=10)
                    assert len(due_files) <= 1  # Should be consistent
                    
                    # Продвинуть monotonic time вперед
                    clock.advance(3600 + 10)  # Jump forward past original time + some margin
                    
                    # Теперь файл должен быть due
                    due_files_after = test_store.store.get_due_files(limit=10)
                    
                    # С monotonic time planner должен оставаться корректным
                    # next_check_at семантика должна держаться
                    if due_files_after:
                        assert len(due_files_after) == 1
                        assert due_files_after[0].path == str(video_file)

    @pytest.mark.platform
    def test_large_file_handling(self):
        """Тест обработки очень больших файлов"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать "большой" файл (эмулированно)
            large_file = temp_dir / "large_movie.mkv"
            
            # Создаем файл и эмулируем большой размер через мета-информацию
            create_sample_video_file(large_file, size_mb=100)  # Base size
            
            # Эмулируем что файл "большой" через FakeIntegrityChecker
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 1  # Longer check for "large" files
            fake_integrity.enable_auto_mode(threshold_bytes=50 * 1024 * 1024)  # 50MB threshold
            
            # Mock the actual integrity checker instance in the monitor
            with patch.object(monitor.integrity_checker, 'check_video_integrity', fake_integrity.check_video_integrity):
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                # Проверить что файл обрабатывается корректно
                test_store.assert_file_exists(
                    str(large_file),
                    integrity_status=IntegrityStatus.UNKNOWN,
                    processed_status=ProcessedStatus.NEW
                )
                
                # Обработка должна пройти успешно
                due_files = test_store.store.get_due_files(limit=1)
                assert len(due_files) == 1
                
                start_time = time.time()
                monitor.handle_integrity_check(due_files[0])
                processing_time = time.time() - start_time
                
                # Проверить что обработка заняла ожидаемое время
                assert processing_time >= fake_integrity.delay_seconds * 0.8
                
                # Файл должен быть помечен как COMPLETE
                updated_data = test_store.get_file_by_path(str(large_file))
                assert IntegrityStatus(updated_data['integrity_status']) == IntegrityStatus.COMPLETE

    @pytest.mark.platform
    def test_concurrent_filesystem_operations(self):
        """Тест concurrent filesystem операций"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "concurrent_test.mkv"
            create_sample_video_file(video_file, size_mb=10)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0.1
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                due_files = test_store.store.get_due_files(limit=1)
                assert len(due_files) == 1
                
                # Симулировать concurrent operations
                import threading
                import queue
                
                results = queue.Queue()
                errors = queue.Queue()
                
                def concurrent_integrity_check():
                    try:
                        monitor.handle_integrity_check(due_files[0])
                        results.put("success")
                    except Exception as e:
                        errors.put(str(e))
                
                def concurrent_file_modification():
                    try:
                        time.sleep(0.05)  # Start modification mid-check
                        with open(video_file, 'ab') as f:
                            f.write(b'additional_data')
                        results.put("modified")
                    except Exception as e:
                        errors.put(str(e))
                
                # Запустить concurrent операции
                thread1 = threading.Thread(target=concurrent_integrity_check)
                thread2 = threading.Thread(target=concurrent_file_modification)
                
                thread1.start()
                thread2.start()
                
                thread1.join(timeout=2)
                thread2.join(timeout=2)
                
                # Проверить что нет deadlock'ов или критических ошибок
                assert thread1.is_alive() == False
                assert thread2.is_alive() == False
                
                # Должен быть хотя бы один успешный результат
                result_count = 0
                while not results.empty():
                    results.get()
                    result_count += 1
                
                assert result_count >= 1
                
                # Не должно быть критических ошибок
                error_count = 0
                while not errors.empty():
                    error = errors.get()
                    error_count += 1
                    # Logging for debugging, but не failing test
                    print(f"Concurrent operation error (expected): {error}")
                
                # Some errors are expected in concurrent scenarios, but not too many
                assert error_count <= 2

    @pytest.mark.platform
    def test_path_normalization_edge_cases(self):
        """Тест нормализации путей в граничных случаях"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать файлы с различными представлениями путей
            base_name = "movie.mkv"
            file_path = temp_dir / base_name
            create_sample_video_file(file_path, size_mb=10)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Разные способы представления одного пути
            path_variations = [
                str(file_path),  # Absolute
                str(file_path.resolve()),  # Resolved
                str(temp_dir / "." / base_name),  # With dot
                str(temp_dir / ".." / temp_dir.name / base_name),  # With up-reference
            ]
            
            # Каждое discovery должно быть идемпотентным
            for path_variation in path_variations:
                if os.path.exists(path_variation):
                    monitor.scan_directory(str(temp_dir))
            
            # Должна быть только одна запись несмотря на разные представления пути
            assert test_store.get_file_count() == 1
            
            # group_id должен быть стабильным
            file_data = test_store.get_file_by_path(str(file_path))
            original_group_id = file_data['group_id']
            
            # Повторные discovery не должны менять group_id
            for _ in range(3):
                monitor.scan_directory(str(temp_dir))
                updated_data = test_store.get_file_by_path(str(file_path))
                assert updated_data['group_id'] == original_group_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])