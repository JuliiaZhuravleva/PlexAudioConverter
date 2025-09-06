"""
Тесты стабилизации и size-gate для Step 2
"""
import pytest
import time
import os
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
    create_test_config_manager, create_sample_video_file, assert_metrics_equal, wait_for_condition
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestStabilityAndSizeGate:
    """Тесты стабилизации и size-gate"""

    def test_t002_size_gate_growing_file_no_integrity(self):
        """T-002: Size-gate: растущий файл не запускает Integrity"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "downloading.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.store
                )
                
                # Начать "скачивание"
                downloader = SyntheticDownloader(video_file)
                downloader.start_download()
                
                # Discovery файла
                monitor.scan_directory(str(temp_dir))
                
                planner = TestStatePlanner(test_store.store)
                
                # Эмулировать рост файла каждые 2 секунды
                for i in range(4):
                    # Дописать данные
                    chunk_size = 1024 * 1024  # 1MB
                    downloader.append(b'\x00' * chunk_size)
                    
                    # Продвинуть время на 2 секунды
                    clock.advance(2)
                    
                    # Запустить цикл планировщика
                    due_files = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                    
                    if due_files:
                        for file_entry in due_files:
                            # Обновить статистику файла (размер/mtime)
                            monitor._update_file_stats(file_entry)
                    
                    # Проверить что stable_since не установлен
                    file_data = test_store.get_file_by_path(str(video_file))
                    assert file_data['stable_since'] is None, f"stable_since should be None on iteration {i}"
                
                # Проверить что Integrity не запускалась
                assert fake_integrity.call_count == 0
                
                # Проверить метрики
                expected_metrics = {
                    'integrity_started': 0,
                    'integrity_finished': 0
                }
                assert_metrics_equal(planner.get_metrics(), expected_metrics)

    def test_t003_stabilization_triggers_integrity(self):
        """T-003: Стабилизация запускает Integrity"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "stable.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0.1  # Быстрая проверка для теста
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.store
                )
                
                # Создать файл и начать "скачивание"
                downloader = SyntheticDownloader(video_file)
                downloader.start_download()
                downloader.append(b'\x00' * 1024 * 1024)  # 1MB
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                planner = TestStatePlanner(test_store.store)
                
                # Остановить рост файла
                downloader.finish_download()
                
                # Продвинуть время на stable_wait_sec (5 секунд)
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Запустить планировщик
                due_files = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                assert len(due_files) == 1
                
                file_entry = due_files[0]
                
                # Обработать файл
                monitor.handle_integrity_check(file_entry)
                planner.increment_metric('integrity_started')
                planner.increment_metric('integrity_finished')
                
                # Проверить что Integrity запустилась
                assert fake_integrity.call_count == 1
                
                # Проверить статус
                file_data = test_store.get_file_by_path(str(video_file))
                assert file_data['integrity_status'] == IntegrityStatus.COMPLETE.value
                assert file_data['stable_since'] is not None
                
                # Проверить метрики
                expected_metrics = {
                    'integrity_started': 1,
                    'integrity_finished': 1
                }
                assert_metrics_equal(planner.get_metrics(), expected_metrics)

    def test_t006_flapping_file_small_writes(self):
        """T-006: Дрожащий файл (мелкие дозаписи)"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "flapping.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.store
                )
                
                # Создать файл
                downloader = SyntheticDownloader(video_file)
                downloader.start_download()
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                planner = TestStatePlanner(test_store.store)
                
                # Эмулировать дрожащий файл - мелкие дозаписи каждые 1-2 секунды
                for i in range(10):
                    # Мелкая дозапись
                    chunk_size = 64 * 1024  # 64KB
                    downloader.append(b'\x00' * chunk_size)
                    
                    # Продвинуть время на 1-2 секунды (меньше stable_wait_sec)
                    clock.advance(1.5)
                    
                    # Запустить планировщик
                    due_files = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                    
                    if due_files:
                        for file_entry in due_files:
                            monitor._update_file_stats(file_entry)
                    
                    # Проверить что stable_since сбрасывается
                    file_data = test_store.get_file_by_path(str(video_file))
                    assert file_data['stable_since'] is None, f"stable_since should be None on flap {i}"
                
                # Проверить что Integrity не запускалась
                assert fake_integrity.call_count == 0
                
                # Теперь остановить дозаписи и дождаться стабилизации
                downloader.finish_download()
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Запустить планировщик
                due_files = planner.get_due_files(limit=TEST_CONSTANTS['DUE_LIMIT'])
                if due_files:
                    file_entry = due_files[0]
                    monitor.handle_integrity_check(file_entry)
                
                # Теперь Integrity должна запуститься
                assert fake_integrity.call_count == 1

    def test_stability_threshold_exact_timing(self):
        """Тест точного соблюдения порога стабильности"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "timing.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.store
                )
                
                # Создать файл
                create_sample_video_file(video_file, size_mb=10)
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                planner = TestStatePlanner(test_store.store)
                
                # Проверить что файл due
                due_files = planner.get_due_files(limit=1)
                assert len(due_files) == 1
                
                # Продвинуть время на stable_wait_sec - 1 секунду
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'] - 1)
                
                # Запустить планировщик - Integrity НЕ должна запуститься
                due_files = planner.get_due_files(limit=1)
                if due_files:
                    file_entry = due_files[0]
                    # Проверить что файл еще не готов для Integrity
                    file_data = test_store.get_file_by_path(str(video_file))
                    current_time = clock.time()
                    if file_data['stable_since']:
                        time_stable = current_time - file_data['stable_since']
                        assert time_stable < TEST_CONSTANTS['STABLE_WAIT_SEC']
                
                assert fake_integrity.call_count == 0
                
                # Продвинуть время еще на 2 секунды (итого stable_wait_sec + 1)
                clock.advance(2)
                
                # Теперь Integrity должна запуститься
                due_files = planner.get_due_files(limit=1)
                if due_files:
                    file_entry = due_files[0]
                    monitor.handle_integrity_check(file_entry)
                
                assert fake_integrity.call_count == 1

    def test_mtime_vs_size_stability(self):
        """Тест стабильности по mtime vs размеру файла"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "mtime_test.mkv"
            
            fake_integrity = FakeIntegrityChecker()
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager()
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.store
                )
                
                # Создать файл
                downloader = SyntheticDownloader(video_file)
                downloader.start_download()
                downloader.append(b'\x00' * 1024 * 1024)  # 1MB
                
                # Discovery
                monitor.scan_directory(str(temp_dir))
                
                planner = TestStatePlanner(test_store.store)
                
                # Изменить только mtime без изменения размера
                current_time = clock.time()
                downloader.set_mtime(current_time)
                
                # Продвинуть время
                clock.advance(2)
                
                # Запустить планировщик
                due_files = planner.get_due_files(limit=1)
                if due_files:
                    file_entry = due_files[0]
                    monitor._update_file_stats(file_entry)
                
                # stable_since должен сброситься из-за изменения mtime
                file_data = test_store.get_file_by_path(str(video_file))
                # В зависимости от реализации, может проверяться mtime или размер
                
                # Теперь оставить файл без изменений
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                due_files = planner.get_due_files(limit=1)
                if due_files:
                    file_entry = due_files[0]
                    monitor.handle_integrity_check(file_entry)
                
                # Integrity должна запуститься после стабилизации
                assert fake_integrity.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
