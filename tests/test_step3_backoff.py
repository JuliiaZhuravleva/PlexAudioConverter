"""
Заготовки тестов для Step 3 - backoff логика
Эти тесты будут активированы когда Step 3 будет реализован
"""
import pytest
import time
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import (
    TempFS, FakeClock, FakeIntegrityChecker, StateStoreFixture, 
    create_test_config_manager, create_sample_video_file, IntegrityResult
)
from state_management.enums import IntegrityStatus, ProcessedStatus
from core.audio_monitor import AudioMonitor


class TestBackoffLogic:
    """Тесты backoff логики (Step 3)"""

    def test_t101_backoff_after_incomplete(self):
        """T-101: Backoff после INCOMPLETE"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "incomplete.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Настроить FakeIntegrityChecker всегда возвращать INCOMPLETE
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.set_default_result(
                IntegrityResult(status=IntegrityStatus.INCOMPLETE, score=0.3, mode="full")
            )
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager(backoff_step_sec=30, backoff_max_sec=600)
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Регистрируем обработчики для планировщика
                import asyncio
                asyncio.run(monitor.register_planner_handlers())
                
                # 1. Discovery файла
                result = monitor.scan_directory(str(temp_dir))
                assert result['files_added'] == 1
                
                # Получаем файл из store
                file_entry = test_store.store.get_file(video_file)
                assert file_entry is not None
                assert file_entry.integrity_status == IntegrityStatus.UNKNOWN
                assert file_entry.integrity_fail_count == 0
                
                # 2. Первая неудачная проверка целостности
                clock.advance(seconds=35)  # Ждем стабильности
                processed = test_store._process_due_files_sync(1)
                
                # Проверяем что файл перешел в INCOMPLETE с backoff
                file_entry = test_store.store.get_file(video_file)
                assert file_entry.integrity_status == IntegrityStatus.INCOMPLETE
                assert file_entry.integrity_fail_count == 1
                
                # next_check_at должен быть увеличен на backoff_step_sec (30s)
                current_time = int(clock.time())
                expected_next_check = current_time + 30
                assert file_entry.next_check_at >= expected_next_check - 5  # Допуск 5 секунд
                
                # 3. Повторная неудача - backoff должен увеличиться
                clock.advance(seconds=35)  # Ждем окончания backoff
                processed = test_store._process_due_files_sync(1)
                
                file_entry = test_store.store.get_file(video_file)
                assert file_entry.integrity_status == IntegrityStatus.INCOMPLETE
                assert file_entry.integrity_fail_count == 2
                
                # next_check_at должен быть увеличен на backoff_step_sec * 2 (60s)
                current_time = int(clock.time())
                expected_next_check = current_time + 60
                assert file_entry.next_check_at >= expected_next_check - 5  # Допуск 5 секунд

    def test_t102_backoff_reset_on_size_change(self):
        """T-102: Сброс backoff при новом изменении размера"""
        with TempFS() as temp_dir, StateStoreFixture() as test_store, FakeClock() as clock:
            video_file = temp_dir / "growing_again.mkv"
            create_sample_video_file(video_file, size_mb=50)
            
            # Настроить FakeIntegrityChecker возвращать INCOMPLETE
            fake_integrity = FakeIntegrityChecker()
            fake_integrity.set_default_result(
                IntegrityResult(status=IntegrityStatus.INCOMPLETE, score=0.3, mode="full")
            )
            
            with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
                mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
                
                config = create_test_config_manager(backoff_step_sec=30, backoff_max_sec=600)
                monitor = AudioMonitor(
                    config=config,
                    state_store=test_store.store,
                    state_planner=test_store.planner
                )
                
                # Регистрируем обработчики для планировщика
                import asyncio
                asyncio.run(monitor.register_planner_handlers())
                
                # 1. Довести файл до INCOMPLETE с backoff
                monitor.scan_directory(str(temp_dir))
                clock.advance(seconds=35)  # Стабильность
                
                # Симуляция процесса due files
                test_store._process_due_files_sync(1)
                
                # Проверяем что файл в состоянии INCOMPLETE с backoff
                file_entry = test_store.store.get_file(video_file)
                assert file_entry.integrity_status == IntegrityStatus.INCOMPLETE
                assert file_entry.integrity_fail_count == 1
                assert file_entry.stable_since is not None
                
                original_next_check = file_entry.next_check_at
                assert original_next_check > int(clock.time())  # В будущем (backoff)
                
                # 2. Изменить размер файла (симулируем дополнительную запись)
                with open(video_file, 'ab') as f:
                    f.write(b'additional data for size change test')
                
                # 3. Повторный discovery с изменениями
                monitor.scan_directory(str(temp_dir))
                
                # 4. Проверить что stable_since, fail_count и next_check_at сброшены
                file_entry = test_store.store.get_file(video_file)
                assert file_entry.stable_since is None, "stable_since должен быть сброшен"
                assert file_entry.integrity_fail_count == 0, "integrity_fail_count должен быть сброшен"
                assert file_entry.integrity_status == IntegrityStatus.UNKNOWN, "integrity_status должен быть сброшен"
                
                # next_check_at должен быть близко к текущему времени (не в далеком будущем)
                current_time = int(clock.time())
                assert file_entry.next_check_at <= current_time + 5, "next_check_at должен быть близко к текущему времени"
                assert file_entry.next_check_at < original_next_check, "next_check_at должен быть сброшен с backoff"


@pytest.mark.skip(reason="Step 4 not implemented yet") 
class TestEN20Processing:
    """Тесты обработки EN 2.0 (Step 4)"""

    def test_t201_skip_if_has_en20(self):
        """T-201: Skip, если есть EN 2.0"""
        # TODO: Реализовать когда Step 4 будет готов
        assert False, "Test not implemented - waiting for Step 4"

    def test_t202_no_en20_ready_for_conversion(self):
        """T-202: Нет EN 2.0 — готов к конвертации"""
        # TODO: Реализовать когда Step 4 будет готов
        assert False, "Test not implemented - waiting for Step 4"


@pytest.mark.skip(reason="Step 5 not implemented yet")
class TestGroupProcessing:
    """Тесты группировки для delete_original (Step 5)"""

    def test_t301_pair_required_for_group_processed(self):
        """T-301: Пара обязательна для «группа обработана»"""
        # TODO: Реализовать когда Step 5 будет готов
        assert False, "Test not implemented - waiting for Step 5"

    def test_t302_delete_original_true_single_copy_sufficient(self):
        """T-302: delete_original=true — достаточно одной копии"""
        # TODO: Реализовать когда Step 5 будет готов
        assert False, "Test not implemented - waiting for Step 5"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
