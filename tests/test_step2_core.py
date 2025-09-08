"""
Основные тесты для Step 2 - Discovery и планировщик
"""
import pytest
import time
import os
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS,
    create_test_config_manager, create_sample_video_file, assert_metrics_equal
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor
from core.config_manager import ConfigManager


class TestDiscoveryAndPlanning:
    """Тесты Discovery и базового планировщика"""

    def test_t001_discovery_creates_records_no_spinning(self):
        """T-001: Discovery создаёт записи и не спиннит"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать стабильный файл
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Настроить моки
            fake_integrity = FakeIntegrityChecker()
            ffprobe_stub = FFprobeStub()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                # Создать монитор
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Запустить один цикл discovery
                monitor.scan_directory(str(temp_dir))
                
                # Проверить создание записи
                test_store.assert_file_exists(
                    str(video_file),
                    integrity_status=IntegrityStatus.UNKNOWN,
                    processed_status=ProcessedStatus.NEW,
                    is_stereo=False
                )
                
                # Проверить что файл попал в due
                due_files = test_store.store.get_due_files(limit=10)
                assert len(due_files) == 1
                assert due_files[0].path == str(video_file)
                
                # Проверить group_id
                file_data = test_store.get_file_by_path(str(video_file))
                assert file_data['group_id'] is not None
                assert 'movie' in file_data['group_id']

    def test_t005_multiple_files_due_limit(self):
        """T-005: Несколько файлов и DUE_LIMIT"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать 5 стабильных файлов
            video_files = []
            for i in range(5):
                video_file = temp_dir / f"movie_{i}.mkv"
                create_sample_video_file(video_file, size_mb=10)
                video_files.append(video_file)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0.1  # Быстрые проверки для теста
            
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
                
                # Проверить что все файлы в базе
                assert test_store.get_file_count() == 5
                
                # Эмулировать планировщик с DUE_LIMIT=3
                planner = StatePlannerFixture(test_store.store)
                
                # Первый тик - берет 3 файла
                due_files_1 = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                assert len(due_files_1) == 3
                
                # Обработать первый батч
                for file_entry in due_files_1:
                    monitor.handle_integrity_check(file_entry)
                
                # Второй тик - берет оставшиеся 2
                due_files_2 = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                assert len(due_files_2) == 2
                
                # Обработать второй батч
                for file_entry in due_files_2:
                    monitor.handle_integrity_check(file_entry)
                
                # Третий тик - никого не должно быть
                due_files_3 = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                assert len(due_files_3) == 0
                
                # Проверить метрики
                expected_metrics = {
                    'due_picked': 5,  # 3 + 2 + 0
                }
                assert_metrics_equal(planner.get_metrics(), expected_metrics)

    def test_t012_performance_idle(self):
        """T-012: Производительность idle"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            planner = StatePlannerFixture(test_store.store)
            
            # Убедиться что нет due-записей
            test_store.assert_no_due_files()
            
            # Эмулировать несколько idle циклов
            start_time = time.time()
            for _ in range(5):
                due_files = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                assert len(due_files) == 0
                time.sleep(0.01)  # Минимальная пауза
            
            elapsed = time.time() - start_time
            
            # Проверить что время выполнения минимально
            assert elapsed < 0.1, f"Idle cycles took too long: {elapsed}s"
            
            # Проверить метрики
            expected_metrics = {
                'due_picked': 0,
                'integrity_started': 0,
                'integrity_finished': 0
            }
            assert_metrics_equal(planner.get_metrics(), expected_metrics)

    def test_discovery_stereo_detection(self):
        """Тест детекции .stereo файлов"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            # Создать original и stereo файлы
            original_file = temp_dir / "TWD.S01E01.mkv"
            stereo_file = temp_dir / "TWD.S01E01.stereo.mkv"
            
            create_sample_video_file(original_file, size_mb=100)
            create_sample_video_file(stereo_file, size_mb=50)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Discovery
            monitor.scan_directory(str(temp_dir))
            
            # Проверить детекцию is_stereo
            original_data = test_store.get_file_by_path(str(original_file))
            stereo_data = test_store.get_file_by_path(str(stereo_file))
            
            assert original_data['is_stereo'] == False
            assert stereo_data['is_stereo'] == True
            
            # Проверить что group_id одинаковый
            assert original_data['group_id'] == stereo_data['group_id']
            
            # Проверить группу
            assert test_store.get_group_count() == 1

    def test_discovery_idempotent_upsert(self):
        """Тест идемпотентности upsert по path"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store:
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            config = create_test_config_manager()
            monitor = AudioMonitor(
                config=config,
                state_store=test_store.store,
                state_planner=test_store.planner
            )
            
            # Первый discovery
            monitor.scan_directory(str(temp_dir))
            first_count = test_store.get_file_count()
            first_data = test_store.get_file_by_path(str(video_file))
            
            # Второй discovery того же файла
            monitor.scan_directory(str(temp_dir))
            second_count = test_store.get_file_count()
            second_data = test_store.get_file_by_path(str(video_file))
            
            # Проверить что количество не изменилось
            assert first_count == second_count == 1
            
            # Проверить что основные поля не изменились
            assert first_data['id'] == second_data['id']
            assert first_data['group_id'] == second_data['group_id']
            assert first_data['first_seen_at'] == second_data['first_seen_at']

    def test_planning_next_check_at_management(self):
        """Тест управления next_check_at планировщиком"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "movie.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
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
                
                # Получить файл для обработки
                due_files = test_store.store.get_due_files(limit=1)
                assert len(due_files) == 1
                
                file_entry = due_files[0]
                original_next_check = file_entry.next_check_at
                
                # Обработать файл
                monitor.handle_integrity_check(file_entry)
                
                # Проверить что next_check_at изменился
                updated_data = test_store.get_file_by_path(str(video_file))
                assert updated_data['next_check_at'] != original_next_check
                
                # Проверить что файл больше не due
                due_files_after = test_store.store.get_due_files(limit=10)
                assert len(due_files_after) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
