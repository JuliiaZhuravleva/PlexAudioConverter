"""
Тестовые утилиты и фикстуры для системы state-management
"""
import os
import time
import tempfile
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from unittest.mock import Mock, patch
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
import json

from state_management.enums import IntegrityStatus, ProcessedStatus
from state_management.store import StateStore
from state_management.planner import StatePlanner
from state_management.config import StateConfig
from state_management.time_provider import FakeTimeSource, FakeStatProvider, set_time_source, set_stat_provider, reset_to_system


class TempFS:
    """Временная файловая система для тестов"""
    
    def __init__(self):
        self.temp_dir = None
        self.created_files = []
    
    def __enter__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="plex_test_")
        return Path(self.temp_dir)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_file(self, path: Path, content: bytes = b"", mtime: Optional[float] = None):
        """Создать файл с заданным содержимым и временем модификации"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        
        self.created_files.append(path)
        return path


class SyntheticDownloader:
    """Эмулятор загрузки файла порциями"""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.current_size = 0
        self.is_downloading = False
        self._lock = threading.Lock()
    
    def start_download(self):
        """Начать загрузку"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.touch()
        self.is_downloading = True
        self.current_size = 0
    
    def append(self, data: bytes, pause_s: float = 0):
        """Дописать данные в файл с паузой"""
        with self._lock:
            if not self.is_downloading:
                return
            
            with open(self.file_path, 'ab') as f:
                f.write(data)
            
            self.current_size += len(data)
            
            if pause_s > 0:
                time.sleep(pause_s)
    
    def change_size(self, new_size: int):
        """Изменить размер файла"""
        with self._lock:
            if new_size > self.current_size:
                # Увеличить размер
                with open(self.file_path, 'ab') as f:
                    f.write(b'\x00' * (new_size - self.current_size))
            elif new_size < self.current_size:
                # Уменьшить размер
                with open(self.file_path, 'r+b') as f:
                    f.truncate(new_size)
            
            self.current_size = new_size
    
    def set_mtime(self, mtime: float):
        """Установить время модификации"""
        os.utime(self.file_path, (mtime, mtime))
    
    def rename_to(self, new_path: Path):
        """Переименовать файл"""
        new_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.rename(new_path)
        self.file_path = new_path
    
    def delete(self):
        """Удалить файл"""
        if self.file_path.exists():
            self.file_path.unlink()
        self.is_downloading = False
    
    def finish_download(self):
        """Завершить загрузку"""
        self.is_downloading = False


class FakeClock:
    """Управляемое время для тестов"""
    
    def __init__(self, start_time: float = None):
        self.current_time = start_time or time.time()
        self._original_time = time.time
        self._original_monotonic = time.monotonic
        self.monotonic_offset = 0
    
    def __enter__(self):
        self.patch_time = patch('time.time', side_effect=self.time)
        self.patch_monotonic = patch('time.monotonic', side_effect=self.monotonic)
        self.patch_time.start()
        self.patch_monotonic.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.patch_time.stop()
        self.patch_monotonic.stop()
    
    def time(self):
        return self.current_time
    
    def monotonic(self):
        return self.current_time + self.monotonic_offset
    
    def advance(self, seconds: float):
        """Продвинуть время вперед"""
        self.current_time += seconds
    
    def set_time(self, timestamp: float):
        """Установить конкретное время"""
        self.current_time = timestamp
    
    def get_fake_time_source(self) -> FakeTimeSource:
        """Получить FakeTimeSource для использования в новом коде"""
        # Создаем синхронизированный FakeTimeSource
        fake_source = FakeTimeSource(
            initial_wall=self.current_time,
            initial_mono=self.current_time + self.monotonic_offset
        )
        return fake_source


@dataclass
class IntegrityResult:
    status: IntegrityStatus
    score: float
    mode: str
    duration: float = 2.0  # Эмулированная длительность проверки


class FakeIntegrityChecker:
    """Предсказуемый integrity checker для тестов"""
    
    def __init__(self):
        self.results: Dict[str, IntegrityResult] = {}
        self.default_result = IntegrityResult(
            status=IntegrityStatus.COMPLETE,
            score=1.0,
            mode="quick"
        )
        self.call_count = 0
        self.call_history = []
        self.delay_seconds = 2.0
        self.auto_mode = False  # Если True, INCOMPLETE для файлов < auto_threshold
        self.auto_threshold = 1024 * 1024  # 1MB
    
    def set_result_for_file(self, file_path: str, result: IntegrityResult):
        """Установить результат для конкретного файла"""
        self.results[file_path] = result
    
    def set_default_result(self, result: IntegrityResult):
        """Установить результат по умолчанию"""
        self.default_result = result
    
    def enable_auto_mode(self, threshold_bytes: int = 1024 * 1024):
        """Включить автоматический режим: INCOMPLETE для файлов < threshold"""
        self.auto_mode = True
        self.auto_threshold = threshold_bytes
    
    def check_video_integrity(self, file_path: str) -> Tuple[IntegrityStatus, float, str]:
        """Эмулировать проверку целостности"""
        self.call_count += 1
        self.call_history.append(file_path)
        
        # Эмулировать задержку
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        
        # Получить результат
        if file_path in self.results:
            result = self.results[file_path]
        elif self.auto_mode and os.path.exists(file_path):
            # Автоматический режим на основе размера файла
            file_size = os.path.getsize(file_path)
            if file_size < self.auto_threshold:
                result = IntegrityResult(
                    status=IntegrityStatus.INCOMPLETE,
                    score=file_size / self.auto_threshold,
                    mode="auto"
                )
            else:
                result = IntegrityResult(
                    status=IntegrityStatus.COMPLETE,
                    score=1.0,
                    mode="auto"
                )
        else:
            result = self.default_result
        
        return result.status, result.score, result.mode


class FFprobeStub:
    """Заглушка для FFprobe с предсказуемыми результатами"""
    
    def __init__(self):
        self.audio_streams: Dict[str, List[Dict]] = {}
        self.default_streams = []
    
    def set_audio_streams(self, file_path: str, streams: List[Dict]):
        """Установить аудио потоки для файла"""
        self.audio_streams[file_path] = streams
    
    def set_default_streams(self, streams: List[Dict]):
        """Установить потоки по умолчанию"""
        self.default_streams = streams
    
    def add_en_20_stream(self, file_path: str):
        """Добавить EN 2.0 поток для файла"""
        streams = [
            {
                "codec_name": "ac3",
                "channels": 2,
                "tags": {"language": "eng", "title": "English"}
            }
        ]
        self.set_audio_streams(file_path, streams)
    
    def add_no_en_streams(self, file_path: str):
        """Установить отсутствие EN потоков"""
        streams = [
            {
                "codec_name": "ac3", 
                "channels": 6,
                "tags": {"language": "rus", "title": "Russian"}
            }
        ]
        self.set_audio_streams(file_path, streams)
    
    def get_audio_streams(self, file_path: str) -> List[Dict]:
        """Получить аудио потоки файла"""
        return self.audio_streams.get(file_path, self.default_streams)


class StateStoreFixture:
    """Обертка для StateStore с дополнительными методами для тестов"""
    
    def __init__(self, db_path: str = ":memory:"):
        self.config = StateConfig(
            stable_wait_sec=5,  # Уменьшено для тестов
            storage_url=f"file:{db_path}",
            max_state_entries=1000,
            batch_size=3,  # DUE_LIMIT для тестов
            loop_interval_sec=1,
            integrity_quick_mode=True
        )
        # StateStore автоматически инициализируется в конструкторе
        self.store = StateStore(db_path)
        
        # Создаем StatePlanner для этого store с поддержкой TimeSource
        # Используем текущий глобальный TimeSource (может быть подменен в тестах)
        self.planner = StatePlanner(self.store, self.config.__dict__)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.store.close()
    
    def get_file_count(self) -> int:
        """Получить количество файлов"""
        with self.store._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            return cursor.fetchone()[0]
    
    def get_group_count(self) -> int:
        """Получить количество групп"""
        with self.store._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM groups")
            return cursor.fetchone()[0]
    
    def get_file_by_path(self, path: str) -> Optional[Dict]:
        """Получить файл по пути"""
        with self.store._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM files WHERE path = ?", (path,)
            )
            row = cursor.fetchone()
            if row:
                return dict(zip([col[0] for col in cursor.description], row))
            return None
    
    def get_files_by_status(self, integrity_status: IntegrityStatus = None, 
                           processed_status: ProcessedStatus = None) -> List[Dict]:
        """Получить файлы по статусу"""
        conditions = []
        params = []
        
        if integrity_status:
            conditions.append("integrity_status = ?")
            params.append(integrity_status.value)
        
        if processed_status:
            conditions.append("processed_status = ?")
            params.append(processed_status.value)
        
        query = "SELECT * FROM files"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        with self.store._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(zip([col[0] for col in cursor.description], row)) 
                   for row in cursor.fetchall()]
    
    def assert_file_exists(self, path: str, **expected_fields):
        """Проверить существование файла с ожидаемыми полями"""
        file_data = self.get_file_by_path(path)
        assert file_data is not None, f"File {path} not found in database"
        
        for field, expected_value in expected_fields.items():
            actual_value = file_data.get(field)
            if isinstance(expected_value, IntegrityStatus):
                actual_value = IntegrityStatus(actual_value)
            elif isinstance(expected_value, ProcessedStatus):
                actual_value = ProcessedStatus(actual_value)
            
            assert actual_value == expected_value, \
                f"Field {field}: expected {expected_value}, got {actual_value}"
    
    def assert_no_due_files(self):
        """Проверить отсутствие due файлов"""
        due_files = self.store.get_due_files(limit=100)
        assert len(due_files) == 0, f"Expected no due files, got {len(due_files)}"
    
    def _process_due_files_sync(self, limit: int = None) -> int:
        """Синхронная обертка для process_due_files для тестов"""
        import asyncio
        
        # Сохраняем оригинальный метод
        original_method = self.planner.process_due_files
        
        try:
            return asyncio.run(original_method(limit))
        except RuntimeError:
            # Если asyncio.run не работает, пытаемся через get_event_loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(original_method(limit))
            finally:
                loop.close()


class StatePlannerFixture:
    """Обертка для StatePlanner с метриками для тестов"""
    
    def __init__(self, store: StateStore):
        self.planner = StatePlanner(store)
        self.metrics = {
            'files_discovered': 0,
            'due_picked': 0,
            'integrity_started': 0,
            'integrity_finished': 0,
            'cycles_run': 0
        }
    
    def get_due_files(self, limit: int = None) -> List:
        """Получить due файлы с учетом метрик"""
        files = self.planner.get_due_files(limit)
        self.metrics['due_picked'] += len(files)
        return files
    
    def increment_metric(self, metric_name: str, value: int = 1):
        """Увеличить метрику"""
        self.metrics[metric_name] = self.metrics.get(metric_name, 0) + value
    
    def get_metrics(self) -> Dict[str, int]:
        """Получить метрики"""
        return self.metrics.copy()
    
    def reset_metrics(self):
        """Сбросить метрики"""
        for key in self.metrics:
            self.metrics[key] = 0


# Константы для тестов
TEST_CONSTANTS = {
    'STABLE_WAIT_SEC': 5,
    'DUE_LIMIT': 3,
    'INTEGRITY_CHECK_DURATION': 2,
    'BATCH_SIZE': 3,
    'LOOP_INTERVAL_SEC': 1
}


def create_test_config(**overrides) -> StateConfig:
    """Создать тестовую конфигурацию StateConfig"""
    defaults = {
        'stable_wait_sec': TEST_CONSTANTS['STABLE_WAIT_SEC'],
        'storage_url': 'file::memory:',
        'max_state_entries': 1000,
        'batch_size': TEST_CONSTANTS['DUE_LIMIT'],
        'loop_interval_sec': TEST_CONSTANTS['LOOP_INTERVAL_SEC'],
        'integrity_quick_mode': True,
        'backoff_step_sec': 30,
        'backoff_max_sec': 600,
        'integrity_timeout_sec': 300
    }
    defaults.update(overrides)
    return StateConfig(**defaults)


def create_test_config_manager(**overrides):
    """Создать тестовый ConfigManager для AudioMonitor"""
    import configparser
    from core.config_manager import ConfigManager
    
    config = configparser.ConfigParser()
    
    # Добавить необходимые секции
    config.add_section('General')
    config.set('General', 'watch_directory', '/tmp/test')
    config.set('General', 'check_interval', '300')
    config.set('General', 'delete_original', 'false')
    
    config.add_section('Download')
    config.set('Download', 'enabled', 'true')
    config.set('Download', 'stability_threshold', '30.0')
    config.set('Download', 'check_interval', '5.0')
    
    config.add_section('Telegram')
    config.set('Telegram', 'enabled', 'false')
    
    config.add_section('FFmpeg')
    config.set('FFmpeg', 'ffmpeg_path', 'ffmpeg')
    config.set('FFmpeg', 'ffprobe_path', 'ffprobe')
    
    # Применить переопределения
    for section_key, value in overrides.items():
        if '.' in section_key:
            section, key = section_key.split('.', 1)
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, key, str(value))
    
    # Создать ConfigManager с этой конфигурацией
    config_manager = ConfigManager.__new__(ConfigManager)
    config_manager.config = config
    config_manager.config_file = 'test_config.ini'  # Добавить обязательный атрибут
    return config_manager


def create_sample_video_file(path: Path, size_mb: int = 100) -> Path:
    """Создать образец видео файла для тестов"""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Создать файл с псевдо-видео содержимым
    content = b'FAKE_VIDEO_HEADER' + b'\x00' * (size_mb * 1024 * 1024 - 17)
    path.write_bytes(content)
    
    return path


def assert_metrics_equal(actual: Dict[str, int], expected: Dict[str, int]):
    """Проверить соответствие метрик"""
    for metric, expected_value in expected.items():
        actual_value = actual.get(metric, 0)
        assert actual_value == expected_value, \
            f"Metric {metric}: expected {expected_value}, got {actual_value}"


def wait_for_condition(condition_func, timeout_sec: float = 10, check_interval: float = 0.1):
    """Ожидать выполнения условия с таймаутом"""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        if condition_func():
            return True
        time.sleep(check_interval)
    return False
