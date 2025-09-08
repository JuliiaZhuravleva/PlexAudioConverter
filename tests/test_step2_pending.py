"""
Тесты защиты PENDING и restart-recovery для Step 2
"""
import pytest
import time
import os
import threading
from pathlib import Path
from unittest.mock import patch, Mock

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
    StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
    create_test_config_manager, create_sample_video_file, assert_metrics_equal, IntegrityResult
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestPendingProtectionAndRecovery:
    """Тесты защиты PENDING и restart-recovery"""

    def test_t004_pending_protects_from_duplicate_capture(self):
        """T-004: PENDING защищает от повторного захвата"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "pending_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Настроить FakeIntegrityChecker с задержкой
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 2.0  # 2 секунды задержки
            
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
                
                planner = StatePlannerFixture(test_store.store)
                
                # Продвинуть время для стабилизации
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                # Первый тик - должен захватить файл и пометить PENDING
                due_files_1 = planner.get_due_files(limit=1)
                assert len(due_files_1) == 1
                
                file_entry = due_files_1[0]
                
                # Запустить integrity check в отдельном потоке
                def run_integrity():
                    monitor.handle_integrity_check(file_entry)
                    planner.increment_metric('integrity_finished')
                
                integrity_thread = threading.Thread(target=run_integrity)
                integrity_thread.start()
                
                # Дать время для установки PENDING статуса
                time.sleep(0.1)
                
                # Проверить что статус PENDING
                file_data = test_store.get_file_by_path(str(video_file))
                assert file_data['integrity_status'] == IntegrityStatus.PENDING.value
                
                # Второй и третий тики во время выполнения - не должны захватывать файл
                for i in range(3):
                    clock.advance(0.5)  # Продвинуть время, но не до окончания проверки
                    due_files_repeat = planner.get_due_files(limit=1)
                    assert len(due_files_repeat) == 0, f"File should not be due during PENDING on iteration {i}"
                
                # Дождаться завершения integrity check
                integrity_thread.join(timeout=5)
                
                # Проверить что проверка завершилась
                file_data_final = test_store.get_file_by_path(str(video_file))
                assert file_data_final['integrity_status'] == IntegrityStatus.COMPLETE.value
                
                # Проверить что integrity запустилась только один раз
                assert fake_integrity.call_count == 1
                
                # Проверить метрики
                expected_metrics = {
                    'integrity_finished': 1
                }
                assert_metrics_equal(planner.get_metrics(), expected_metrics)

    def test_t007_restart_recovery(self):
        """T-007: Restart-recovery"""
        with TempFS() as temp_dir, FakeClock() as clock:
            video_file = temp_dir / "restart_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 0.1
            
            # Создать временный файл БД для имитации перезапуска
            db_file = temp_dir / "test_state.db"
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                # Первый "запуск" процесса
                with StateStoreFixture(db_path=str(db_file)) as test_store_1:
                    config = create_test_config_manager()
                    monitor_1 = AudioMonitor(
                        config=config,
                        state_store=test_store_1.store,
                        state_planner=test_store_1.store
                    )
                    
                    # Discovery и доведение до PENDING
                    monitor_1.scan_directory(str(temp_dir))
                    
                    clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                    
                    due_files = test_store_1.store.get_due_files(limit=1)
                    assert len(due_files) == 1
                    
                    file_entry = due_files[0]
                    
                    # Установить PENDING статус вручную (имитация начала проверки)
                    test_store_1.store.upsert_file(
                        path=str(video_file),
                        size_bytes=file_entry.size_bytes,
                        mtime=file_entry.mtime,
                        integrity_status=IntegrityStatus.PENDING,
                        next_check_at=clock.time() + 10  # Защитный timeout
                    )
                    
                    # Проверить что файл в PENDING
                    pending_data = test_store_1.get_file_by_path(str(video_file))
                    assert pending_data['integrity_status'] == IntegrityStatus.PENDING.value
                
                # "Перезапуск" процесса - создать новый экземпляр с той же БД
                with StateStoreFixture(db_path=str(db_file)) as test_store_2:
                    config = create_test_config_manager()
                    monitor_2 = AudioMonitor(
                        config=config,
                        state_store=test_store_2.store,
                        state_planner=test_store_2.store
                    )
                    
                    # Проверить что состояние восстановилось
                    recovered_data = test_store_2.get_file_by_path(str(video_file))
                    assert recovered_data is not None
                    assert recovered_data['integrity_status'] == IntegrityStatus.PENDING.value
                    
                    # Проверить что файл не берется в due до истечения timeout
                    due_files_after_restart = test_store_2.store.get_due_files(limit=10)
                    assert len(due_files_after_restart) == 0
                    
                    # Продвинуть время за timeout
                    clock.advance(15)
                    
                    # Теперь файл должен снова стать due
                    due_files_after_timeout = test_store_2.store.get_due_files(limit=10)
                    assert len(due_files_after_timeout) == 1
                    
                    # Завершить проверку
                    file_entry_recovered = due_files_after_timeout[0]
                    monitor_2.handle_integrity_check(file_entry_recovered)
                    
                    # Проверить финальный статус
                    final_data = test_store_2.get_file_by_path(str(video_file))
                    assert final_data['integrity_status'] == IntegrityStatus.COMPLETE.value

    def test_pending_timeout_recovery(self):
        """Тест восстановления после timeout PENDING статуса"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "timeout_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            fake_integrity = FakeIntegrityChecker()
            
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
                
                # Установить PENDING статус с истекшим timeout
                past_time = clock.time() - 100  # 100 секунд назад
                test_store.store.upsert_file(
                    path=str(video_file),
                    size_bytes=1024*1024*50,
                    mtime=clock.time(),
                    integrity_status=IntegrityStatus.PENDING,
                    next_check_at=past_time  # Уже истек
                )
                
                planner = StatePlannerFixture(test_store.store)
                
                # Файл должен стать due из-за истекшего timeout
                due_files = planner.get_due_files(limit=1)
                assert len(due_files) == 1
                
                # Обработать файл
                file_entry = due_files[0]
                monitor.handle_integrity_check(file_entry)
                
                # Проверить что статус обновился
                final_data = test_store.get_file_by_path(str(video_file))
                assert final_data['integrity_status'] == IntegrityStatus.COMPLETE.value

    def test_concurrent_access_protection(self):
        """Тест защиты от конкурентного доступа"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "concurrent_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.delay_seconds = 1.0
            
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
                
                clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                
                planner = StatePlannerFixture(test_store.store)
                
                # Два "планировщика" пытаются захватить один файл
                due_files_1 = planner.get_due_files(limit=1)
                due_files_2 = planner.get_due_files(limit=1)
                
                assert len(due_files_1) == 1
                assert len(due_files_2) == 0  # Второй не должен получить файл
                
                # Или если оба получили, то это один и тот же файл
                if len(due_files_2) > 0:
                    assert due_files_1[0].id == due_files_2[0].id

    def test_pending_status_transitions(self):
        """Тест корректных переходов статуса PENDING"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "transitions_test.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Тест различных результатов integrity
            test_cases = [
                (IntegrityStatus.COMPLETE, 1.0, "quick"),
                (IntegrityStatus.INCOMPLETE, 0.5, "full"),
                (IntegrityStatus.ERROR, 0.0, "error")
            ]
            
            for expected_status, score, mode in test_cases:
                fake_integrity = FakeIntegrityChecker()
                fake_integrity.set_default_result(
                    IntegrityResult(status=expected_status, score=score, mode=mode)
                )
                
                with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                    mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                    
                    config = create_test_config_manager()
                    monitor = AudioMonitor(
                        config=config,
                        state_store=test_store.store,
                        state_planner=test_store.planner
                    )
                    
                    # Сбросить статус файла
                    test_store.store.upsert_file(
                        path=str(video_file),
                        size_bytes=1024*1024*50,
                        mtime=clock.time(),
                        integrity_status=IntegrityStatus.UNKNOWN,
                        next_check_at=clock.time()
                    )
                    
                    clock.advance(TEST_CONSTANTS['STABLE_WAIT_SEC'])
                    
                    # Получить и обработать файл
                    due_files = test_store.store.get_due_files(limit=1)
                    if due_files:
                        file_entry = due_files[0]
                        monitor.handle_integrity_check(file_entry)
                    
                    # Проверить финальный статус
                    final_data = test_store.get_file_by_path(str(video_file))
                    assert final_data['integrity_status'] == expected_status.value
                    assert abs(final_data['integrity_score'] - score) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
