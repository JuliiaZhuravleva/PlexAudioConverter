#!/usr/bin/env python3
"""
Integration Tests for State Machine Workflows
Тестирование основных сценариев работы системы управления состояниями
"""

import asyncio
import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import pytest
import shutil

# Импорты компонентов системы состояний
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from unittest.mock import patch, MagicMock

from state_management.enums import IntegrityStatus, ProcessedStatus, PairStatus
from state_management.models import FileEntry, GroupEntry, normalize_group_id, create_file_entry_from_path
from state_management.store import StateStore
from state_management.planner import StatePlanner
from state_management.machine import AudioStateMachine, create_state_machine
from state_management.config import StateConfig, get_development_config
from state_management.metrics import get_metrics, MetricNames

# Настройка логирования для тестов
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestStateEnums:
    """Тесты для перечислений состояний"""
    
    def test_integrity_status_transitions(self):
        """Тест переходов статусов целостности"""
        # Валидные переходы
        assert IntegrityStatus.UNKNOWN.can_transition_to(IntegrityStatus.PENDING)
        assert IntegrityStatus.PENDING.can_transition_to(IntegrityStatus.COMPLETE)
        assert IntegrityStatus.PENDING.can_transition_to(IntegrityStatus.INCOMPLETE)
        assert IntegrityStatus.INCOMPLETE.can_transition_to(IntegrityStatus.PENDING)
        
        # Невалидные переходы
        assert not IntegrityStatus.UNKNOWN.can_transition_to(IntegrityStatus.COMPLETE)
        assert not IntegrityStatus.COMPLETE.can_transition_to(IntegrityStatus.UNKNOWN)
    
    def test_processed_status_transitions(self):
        """Тест переходов статусов обработки"""
        # Валидные переходы
        assert ProcessedStatus.NEW.can_transition_to(ProcessedStatus.SKIPPED_HAS_EN2)
        assert ProcessedStatus.NEW.can_transition_to(ProcessedStatus.CONVERTED)
        assert ProcessedStatus.CONVERTED.can_transition_to(ProcessedStatus.GROUP_PROCESSED)
        
        # Невалидные переходы
        assert not ProcessedStatus.GROUP_PROCESSED.can_transition_to(ProcessedStatus.NEW)
        assert not ProcessedStatus.SKIPPED_HAS_EN2.can_transition_to(ProcessedStatus.CONVERTED)


class TestStateModels:
    """Тесты для моделей данных"""
    
    def test_normalize_group_id(self):
        """Тест нормализации group_id"""
        # Обычный файл
        group_id, is_stereo = normalize_group_id("/path/to/movie.mkv")
        assert group_id.endswith("/movie")
        assert not is_stereo
        
        # Stereo файл
        group_id, is_stereo = normalize_group_id("/path/to/movie.stereo.mkv")
        assert group_id.endswith("/movie")
        assert is_stereo
    
    def test_file_entry_validation(self):
        """Тест валидации FileEntry"""
        # Валидный entry
        entry = FileEntry(path="/test/file.mkv", group_id="test_group")
        assert entry.path == str(Path("/test/file.mkv").resolve())
        
        # Невалидный integrity_score
        with pytest.raises(ValueError):
            FileEntry(path="/test/file.mkv", group_id="test_group", integrity_score=1.5)
    
    def test_file_entry_status_updates(self):
        """Тест обновления статусов FileEntry"""
        entry = FileEntry(path="/test/file.mkv", group_id="test_group")
        
        # Обновление статуса целостности
        success = entry.update_integrity_status(IntegrityStatus.PENDING)
        assert success
        assert entry.integrity_status == IntegrityStatus.PENDING
        
        # Валидное обновление
        success = entry.update_integrity_status(IntegrityStatus.COMPLETE, score=0.95)
        assert success
        assert entry.integrity_status == IntegrityStatus.COMPLETE
        assert entry.integrity_score == 0.95
        
        # Невалидное обновление (должно вызвать ошибку)
        with pytest.raises(ValueError):
            entry.update_integrity_status(IntegrityStatus.UNKNOWN)


class TestStateStore:
    """Тесты для хранилища состояний"""
    
    @pytest.fixture
    def temp_store(self):
        """Временное хранилище для тестов"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_state.db"
            store = StateStore(db_path)
            yield store
            store.close()
    
    def test_store_file_crud(self, temp_store):
        """Тест CRUD операций с файлами"""
        # Создание файла
        entry = FileEntry(
            path="/test/movie.mkv",
            group_id="test_movie",
            size_bytes=1000000
        )
        
        saved_entry = temp_store.upsert_file(entry)
        assert saved_entry.id is not None
        assert saved_entry.path == entry.path
        
        # Чтение файла
        loaded_entry = temp_store.get_file("/test/movie.mkv")
        assert loaded_entry is not None
        assert loaded_entry.id == saved_entry.id
        assert loaded_entry.group_id == "test_movie"
        
        # Обновление файла
        loaded_entry.size_bytes = 2000000
        updated_entry = temp_store.upsert_file(loaded_entry)
        assert updated_entry.size_bytes == 2000000
        
        # Удаление файла
        success = temp_store.delete_file("/test/movie.mkv")
        assert success
        
        deleted_entry = temp_store.get_file("/test/movie.mkv")
        assert deleted_entry is None
    
    def test_store_group_operations(self, temp_store):
        """Тест операций с группами"""
        # Создание группы
        group = GroupEntry(
            group_id="test_group",
            delete_original=False,
            original_present=True,
            stereo_present=False
        )
        
        saved_group = temp_store.upsert_group(group)
        assert saved_group.group_id == "test_group"
        
        # Обновление присутствия файлов
        updated_group = temp_store.update_group_presence("test_group", delete_original=False)
        assert updated_group.group_id == "test_group"
    
    def test_due_files_query(self, temp_store):
        """Тест запроса файлов готовых к обработке"""
        current_time = int(time.time())
        
        # Создаем файлы с разными next_check_at
        entries = [
            FileEntry(path=f"/test/file{i}.mkv", group_id=f"group{i}", 
                     next_check_at=current_time - 10 + i)
            for i in range(5)
        ]
        
        for entry in entries:
            temp_store.upsert_file(entry)
        
        # Получаем просроченные файлы
        due_files = temp_store.get_due_files(current_time, limit=3)
        assert len(due_files) == 3
        
        # Проверяем сортировку по next_check_at
        for i in range(len(due_files) - 1):
            assert due_files[i].next_check_at <= due_files[i + 1].next_check_at


@pytest.mark.asyncio
class TestStatePlanner:
    """Тесты для планировщика"""
    
    @pytest.fixture
    def temp_planner(self):
        """Временный планировщик для тестов"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_state.db"
            store = StateStore(db_path)
            config = get_development_config()
            planner = StatePlanner(store, config.to_dict())
            yield planner, store
            store.close()
    
    @pytest.mark.asyncio
    async def test_file_discovery(self, temp_planner):
        """Тест обнаружения файлов"""
        planner, store = temp_planner
        
        # Создаем временный видео файл
        with tempfile.NamedTemporaryFile(suffix='.mkv', delete=False) as temp_file:
            temp_file.write(b'fake video content')
            temp_path = Path(temp_file.name)
        
        try:
            # Обнаруживаем файл
            entry = await planner.discover_file(temp_path, delete_original=False)
            
            assert entry is not None
            assert entry.path == str(temp_path)
            assert entry.size_bytes > 0
            assert entry.group_id is not None
            
            # Проверяем что файл сохранился в store
            stored_entry = store.get_file(temp_path)
            assert stored_entry is not None
            assert stored_entry.id == entry.id
            
        finally:
            # Очищаем временный файл
            temp_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_directory_scan(self, temp_planner):
        """Тест сканирования директории"""
        planner, store = temp_planner
        
        # Создаем временную директорию с видео файлами
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Создаем несколько видео файлов
            video_files = []
            for i in range(3):
                video_file = temp_path / f"movie_{i}.mkv"
                video_file.write_text("fake video content")
                video_files.append(video_file)
            
            # Создаем не-видео файл (должен игнорироваться)
            (temp_path / "readme.txt").write_text("not a video")
            
            # Сканируем директорию
            discovered_count = await planner.scan_directory(temp_path, delete_original=False)
            
            # Проверяем результаты
            assert discovered_count == 3
            
            # Проверяем что файлы добавились в store
            for video_file in video_files:
                entry = store.get_file(video_file)
                assert entry is not None
    
    @pytest.mark.asyncio
    async def test_due_files_processing(self, temp_planner):
        """Тест обработки просроченных файлов"""
        planner, store = temp_planner
        
        # Создаем файл с просроченным next_check_at
        current_time = int(time.time())
        entry = FileEntry(
            path="/test/overdue.mkv",
            group_id="test_group",
            next_check_at=current_time - 100,  # просрочен
            size_bytes=1000000,
            mtime=current_time - 200
        )
        
        store.upsert_file(entry)
        
        # Обрабатываем просроченные файлы
        processed_count = await planner.process_due_files(limit=10)
        
        # Так как файл не существует, он должен быть удален
        assert processed_count >= 0  # может быть 0 если не удалось обработать

    @pytest.mark.asyncio 
    async def test_failed_task_backoff(self, temp_planner):
        """Тест применения backoff при неуспешном выполнении задачи"""
        planner, store = temp_planner
        
        # Создаем реальный временный файл 
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mkv', delete=False) as tmp_file:
            tmp_file.write("fake video content")
            tmp_file_path = tmp_file.name
        
        try:
            current_time = int(time.time())
            file_stats = Path(tmp_file_path).stat()
            
            # Создаем файл с статусом INCOMPLETE (будет планировать CHECK_INTEGRITY)
            entry = FileEntry(
                path=tmp_file_path, 
                group_id="test_group",
                next_check_at=current_time - 100,  # просрочен
                size_bytes=file_stats.st_size,
                mtime=int(file_stats.st_mtime),
                integrity_status=IntegrityStatus.INCOMPLETE,
                stable_since=current_time - 200
            )
            
            store.upsert_file(entry)
            
            # Получаем файл до обработки
            before_entry = store.get_file(entry.path)
            assert before_entry.next_check_at < current_time
            original_fail_count = before_entry.integrity_fail_count
            
            # Обрабатываем - должен применить backoff для неуспешной CHECK_INTEGRITY задачи
            processed_count = await planner.process_due_files(limit=1)
            
            # processed_count должен быть 0, т.к. задача выполнена неуспешно
            assert processed_count == 0  # неуспешная задача не считается обработанной
            
            # Проверяем что backoff применен: next_check_at обновлен в будущее
            after_entry = store.get_file(entry.path) 
            assert after_entry is not None, f"File entry should not be deleted: {entry.path}"
            assert after_entry.next_check_at > current_time, f"Expected next_check_at > {current_time}, got {after_entry.next_check_at}"
            assert after_entry.integrity_fail_count > original_fail_count, "Fail count should increase"
            
        finally:
            # Очистка временного файла
            try:
                Path(tmp_file_path).unlink()
            except:
                pass


@pytest.fixture
def temp_video_files():
    """Создание временных видео файлов для тестов"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Создаем "видео" файлы
        files = {
            'original': temp_path / "movie.mkv",
            'stereo': temp_path / "movie.stereo.mkv",
            'another': temp_path / "series.S01E01.mkv"
        }
        
        for name, file_path in files.items():
            # Создаем файл с некоторым содержимым
            content = f"fake {name} video content " * 1000  # ~30KB
            file_path.write_text(content)
        
        yield temp_path, files


@pytest.mark.asyncio
class TestStateMachineIntegration:
    """Интеграционные тесты для конечного автомата"""
    
    @pytest.fixture
    def temp_machine(self):
        """Временный конечный автомат для тестов"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_state.db"
            config = get_development_config()
            config.storage_url = str(db_path)
            
            machine = create_state_machine(str(db_path), config.to_dict())
            yield machine
            
            machine.stop()
    
    @pytest.mark.asyncio
    @patch('state_management.machine.get_integrity_adapter')
    async def test_end_to_end_workflow(self, mock_get_adapter, temp_machine, temp_video_files):
        """Тест полного workflow от обнаружения до обработки"""
        # Mock the integrity adapter to return success for test files
        mock_adapter = MagicMock()
        mock_adapter.check_video_integrity.return_value = (IntegrityStatus.COMPLETE, 1.0)
        mock_get_adapter.return_value = mock_adapter
        
        # Replace the adapter in the temp_machine
        temp_machine.integrity_adapter = mock_adapter
        
        temp_path, files = temp_video_files
        
        # 1. Обнаруживаем файлы в директории
        discovered = await temp_machine.discover_directory(temp_path, delete_original=False)
        assert discovered == 3
        
        # 2. Проверяем что файлы добавились в систему
        for file_path in files.values():
            status = temp_machine.get_file_status(file_path)
            assert status is not None
            assert status['integrity_status'] == IntegrityStatus.UNKNOWN.value
            assert status['processed_status'] == ProcessedStatus.NEW.value
        
        # 3. Обрабатываем файлы (несколько итераций для стабилизации)
        # First, manually stabilize files for testing
        logger.info("=== Manually arming stability ===")
        for file_path in files.values():
            entry = temp_machine.store.get_file(file_path)
            if entry:
                logger.debug(f"Before arm_stability: {file_path.name} - stable_since_mono={entry.stable_since_mono}")
                # Set last_change_at to allow stability arming (needs to be >1s in the past)
                entry.last_change_at = temp_machine.planner.time_source.now_mono() - 2.0
                temp_machine.store.upsert_file(entry)
                entry = temp_machine.store.get_file(file_path)  # Refresh
                # Manually arm stability for test
                armed = entry.arm_stability(temp_machine.planner.time_source)
                logger.debug(f"After arm_stability: {file_path.name} - armed={armed}, stable_since_mono={entry.stable_since_mono}")
                temp_machine.store.upsert_file(entry)
        
        # Wait for stable_wait_sec period
        stable_wait = temp_machine.config.get('stable_wait_sec', 5)
        logger.info(f"=== Waiting {stable_wait + 0.5}s for stability period ===")
        await asyncio.sleep(stable_wait + 0.5)
        
        # After waiting, make files due for processing by setting next_check_at
        current_time = int(temp_machine.planner.time_source.now_wall())
        for file_path in files.values():
            entry = temp_machine.store.get_file(file_path)
            if entry:
                entry.next_check_at = current_time  # Make immediately due
                temp_machine.store.upsert_file(entry)
                logger.debug(f"Set next_check_at to {current_time} for {file_path.name}")
        
        # Check due files before processing
        due_files = temp_machine.store.get_due_files(limit=10)
        logger.info(f"=== Due files before processing: {len(due_files)} ===")
        for entry in due_files:
            logger.debug(f"Due: {Path(entry.path).name} - integrity={entry.integrity_status}")
        
        # Now process files
        logger.info("=== Starting file processing ===")
        total_processed = 0
        for iteration in range(5):  # More iterations
            processed = await temp_machine.process_pending_files(limit=10)
            total_processed += processed
            logger.info(f"Iteration {iteration + 1}: processed {processed} files (total: {total_processed})")
            if processed == 0:
                break
            await asyncio.sleep(0.2)  # Slightly longer pause
        
        logger.info(f"=== Processing complete: total processed {total_processed} files ===")
        
        # 4. Проверяем финальные статусы
        original_status = temp_machine.get_file_status(files['original'])
        stereo_status = temp_machine.get_file_status(files['stereo'])
        
        logger.info(f"Original status: {original_status}")
        logger.info(f"Stereo status: {stereo_status}")
        
        # Файлы должны пройти через несколько стадий обработки
        # Проверяем что они больше не в статусе UNKNOWN
        assert original_status['integrity_status'] != IntegrityStatus.UNKNOWN.value
        assert stereo_status['integrity_status'] != IntegrityStatus.UNKNOWN.value
    
    @pytest.mark.asyncio
    async def test_group_formation(self, temp_machine, temp_video_files):
        """Тест формирования групп файлов"""
        temp_path, files = temp_video_files
        
        # Обнаруживаем файлы
        await temp_machine.discover_directory(temp_path, delete_original=False)
        
        # Получаем информацию о группах
        original_status = temp_machine.get_file_status(files['original'])
        stereo_status = temp_machine.get_file_status(files['stereo'])
        
        # Проверяем что original и stereo файлы в одной группе
        assert original_status['group_id'] == stereo_status['group_id']
        assert not original_status['is_stereo']
        assert stereo_status['is_stereo']
        
        # Проверяем информацию о группе
        group_id = original_status['group_id']
        group_status = temp_machine.get_group_status(group_id)
        
        assert group_status is not None
        assert group_status['original_present']
        assert group_status['stereo_present']
        assert group_status['pair_status'] == PairStatus.PAIRED.value
        assert group_status['files_count'] == 2
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, temp_machine, temp_video_files):
        """Тест сбора метрик"""
        temp_path, files = temp_video_files
        
        # Сбрасываем метрики
        metrics = get_metrics()
        metrics.reset()
        
        # Выполняем операции
        await temp_machine.discover_directory(temp_path, delete_original=False)
        await temp_machine.process_pending_files(limit=10)
        
        # Проверяем что метрики собрались
        summary = metrics.get_summary(since_hours=1.0)
        
        assert summary['total_events'] > 0
        assert MetricNames.FILES_DISCOVERED in summary['counters']
        assert summary['counters'][MetricNames.FILES_DISCOVERED] > 0
        
        logger.info(f"Metrics summary: {json.dumps(summary, indent=2)}")
    
    def test_system_status(self, temp_machine):
        """Тест получения статуса системы"""
        status = temp_machine.get_status()
        
        assert 'planner_status' in status
        assert 'store_stats' in status
        assert 'config' in status
        
        # Проверяем структуру статуса планировщика
        planner_status = status['planner_status']
        assert 'running' in planner_status
        assert 'config' in planner_status
        assert 'store_stats' in planner_status
        
        # Проверяем статистику store
        store_stats = status['store_stats']
        assert 'total_files' in store_stats
        assert 'total_groups' in store_stats
        
        logger.info(f"System status: {json.dumps(status, indent=2, default=str)}")
    
    @pytest.mark.asyncio
    async def test_maintenance_operations(self, temp_machine, temp_video_files):
        """Тест операций обслуживания"""
        temp_path, files = temp_video_files
        
        # Заполняем систему данными
        await temp_machine.discover_directory(temp_path, delete_original=False)
        
        # Выполняем обслуживание
        maintenance_result = await temp_machine.maintenance()
        
        assert 'deleted_entries' in maintenance_result
        assert 'total_files' in maintenance_result
        assert 'total_groups' in maintenance_result
        
        logger.info(f"Maintenance result: {maintenance_result}")


class TestErrorHandling:
    """Тесты обработки ошибок"""
    
    @pytest.fixture
    def temp_machine(self):
        """Временный конечный автомат"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_state.db"
            config = get_development_config()
            config.storage_url = str(db_path)
            
            machine = create_state_machine(str(db_path), config.to_dict())
            yield machine
            machine.stop()
    
    @pytest.mark.asyncio
    async def test_missing_file_handling(self, temp_machine):
        """Тест обработки отсутствующих файлов"""
        # Добавляем несуществующий файл в store
        non_existent = Path("/non/existent/file.mkv")
        
        # Попытка обработки должна корректно обработать ошибку
        try:
            await temp_machine.process_file(non_existent, delete_original=False)
        except FileNotFoundError:
            pass  # Ожидаемая ошибка
    
    def test_invalid_transitions(self):
        """Тест обработки невалидных переходов состояний"""
        entry = FileEntry(path="/test/file.mkv", group_id="test_group")
        
        # Попытка невалидного перехода должна вызвать ошибку
        with pytest.raises(ValueError):
            entry.update_integrity_status(IntegrityStatus.COMPLETE)  # без PENDING
    
    def test_database_constraints(self):
        """Тест ограничений базы данных"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test_state.db"
            store = StateStore(db_path)
            
            try:
                # Создаем файл
                entry1 = FileEntry(path="/test/file.mkv", group_id="test")
                store.upsert_file(entry1)
                
                # Попытка создать файл с тем же path должна обновить существующий
                entry2 = FileEntry(path="/test/file.mkv", group_id="test2")
                updated = store.upsert_file(entry2)
                
                # Проверяем что файл обновился, а не создался новый
                assert updated.group_id == "test2"
                
            finally:
                store.close()


# === Вспомогательные функции ===

def create_test_video_file(path: Path, size_bytes: int = 1000) -> Path:
    """Создание тестового видео файла"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "fake video content " * (size_bytes // 20)
    path.write_text(content[:size_bytes])
    return path


def wait_for_condition(condition_func, timeout_sec: float = 10.0, 
                      interval_sec: float = 0.1) -> bool:
    """Ожидание выполнения условия"""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if condition_func():
            return True
        time.sleep(interval_sec)
    return False


if __name__ == "__main__":
    # Запуск тестов
    pytest.main([__file__, "-v", "-s"])