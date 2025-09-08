"""
Централизованные pytest фикстуры для strong test system
"""
import pytest
import tempfile
import shutil
import os
import time
import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch

from tests.fixtures import (
    TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, 
    FFprobeStub, StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS,
    create_test_config, create_test_config_manager, create_sample_video_file
)
from state_management.enums import IntegrityStatus, ProcessedStatus


# Cross-platform event loop policy for consistent async behavior
@pytest.fixture(scope="session")
def event_loop_policy():
    """Set cross-platform event loop policy for consistent async test behavior"""
    if sys.platform == "win32":
        # Use ProactorEventLoop on Windows for better subprocess/file handling
        policy = asyncio.WindowsProactorEventLoopPolicy()
    else:
        # Use default selector event loop on Unix systems  
        policy = asyncio.DefaultEventLoopPolicy()
    
    old_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(policy)
    
    yield policy
    
    # Restore original policy
    asyncio.set_event_loop_policy(old_policy)


@pytest.fixture(scope="function")
def event_loop(event_loop_policy):
    """Create a new event loop for each test"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture
def temp_fs():
    """Temporary filesystem fixture"""
    with TempFS() as temp_dir:
        yield temp_dir


@pytest.fixture
def state_store():
    """State store fixture with temporary database"""
    with StateStoreFixture() as store:
        yield store


@pytest.fixture
def fake_clock():
    """Controlled time fixture"""
    with FakeClock() as clock:
        yield clock


@pytest.fixture
def fake_integrity_checker():
    """Fake integrity checker with configurable results"""
    return FakeIntegrityChecker()


@pytest.fixture
def ffprobe_stub():
    """FFprobe stub for audio stream testing"""
    return FFprobeStub()


@pytest.fixture
def test_config():
    """Basic test configuration"""
    return create_test_config()


@pytest.fixture
def test_config_manager():
    """Test configuration manager for AudioMonitor"""
    return create_test_config_manager()


@pytest.fixture
def planner_fixture(state_store):
    """State planner with metrics tracking"""
    return StatePlannerFixture(state_store.store)


@pytest.fixture
def synthetic_downloader():
    """Factory for creating synthetic downloaders"""
    def _create_downloader(file_path: Path):
        return SyntheticDownloader(file_path)
    return _create_downloader


@pytest.fixture
def sample_video_files():
    """Factory for creating sample video files"""
    def _create_files(base_dir: Path, files_config: list) -> Dict[str, Path]:
        """
        Create multiple video files based on configuration
        
        files_config: List of dicts with keys 'name', 'size_mb', 'mtime'
        Returns: Dict mapping name to Path
        """
        result = {}
        for file_config in files_config:
            file_path = base_dir / file_config['name']
            create_sample_video_file(
                file_path, 
                size_mb=file_config.get('size_mb', 50)
            )
            
            # Set custom mtime if provided
            if 'mtime' in file_config:
                os.utime(file_path, (file_config['mtime'], file_config['mtime']))
            
            result[file_config['name']] = file_path
        return result
    
    return _create_files


@pytest.fixture
def mock_audio_monitor(test_config_manager, state_store):
    """Mock AudioMonitor for testing"""
    with patch('core.video_integrity_checker.VideoIntegrityChecker') as mock_checker:
        from core.audio_monitor import AudioMonitor
        
        # Create a mock integrity checker by default
        fake_integrity = FakeIntegrityChecker()
        mock_checker.return_value.check_video_integrity = fake_integrity.check_video_integrity
        
        monitor = AudioMonitor(
            config=test_config_manager,
            state_store=state_store.store,
            state_planner=state_store.store
        )
        
        # Attach fake_integrity for configuration in tests
        monitor._test_fake_integrity = fake_integrity
        monitor._test_mock_checker = mock_checker
        
        yield monitor


@pytest.fixture
def test_constants():
    """Test constants for consistent configuration"""
    return TEST_CONSTANTS


# Utility fixtures for specific test scenarios

@pytest.fixture
def stability_test_setup(temp_fs, state_store, fake_clock):
    """Setup for stability testing with controlled time"""
    return {
        'temp_fs': temp_fs,
        'state_store': state_store,
        'fake_clock': fake_clock,
        'stable_wait_sec': TEST_CONSTANTS['STABLE_WAIT_SEC']
    }


@pytest.fixture
def group_test_setup(temp_fs, state_store):
    """Setup for group-related testing"""
    # Create typical original and stereo files
    original_file = temp_fs / "TWD.S01E01.mkv"
    stereo_file = temp_fs / "TWD.S01E01.stereo.mkv"
    
    create_sample_video_file(original_file, size_mb=100)
    create_sample_video_file(stereo_file, size_mb=50)
    
    return {
        'temp_fs': temp_fs,
        'state_store': state_store,
        'original_file': original_file,
        'stereo_file': stereo_file
    }


@pytest.fixture
def due_limit_test_setup(temp_fs, state_store, test_constants):
    """Setup for DUE_LIMIT testing with multiple files"""
    files = []
    for i in range(5):  # Create 5 test files
        file_path = temp_fs / f"movie_{i}.mkv"
        create_sample_video_file(file_path, size_mb=10 + i*5)
        files.append(file_path)
    
    return {
        'temp_fs': temp_fs,
        'state_store': state_store,
        'files': files,
        'due_limit': test_constants['DUE_LIMIT']
    }


# Parametrized fixtures for cross-cutting variations

@pytest.fixture(params=[True, False])
def delete_original_param(request):
    """Parametrized fixture for delete_original testing"""
    return request.param


@pytest.fixture(params=[
    {"has_en20": True, "channels": 2, "language": "eng"},
    {"has_en20": False, "channels": 6, "language": "rus"}
])
def audio_stream_param(request):
    """Parametrized fixture for audio stream variations"""
    return request.param


@pytest.fixture(params=[
    {"duration": "short", "size_mb": 10},
    {"duration": "long", "size_mb": 500}
])
def file_duration_param(request):
    """Parametrized fixture for file duration/size variations"""
    return request.param


@pytest.fixture(params=[
    IntegrityStatus.COMPLETE,
    IntegrityStatus.INCOMPLETE,
    IntegrityStatus.ERROR
])
def integrity_result_param(request):
    """Parametrized fixture for integrity check results"""
    return request.param


# Platform-specific fixtures

@pytest.fixture
def unicode_filenames():
    """Unicode filename test cases"""
    return [
        "Кино_Фильм.mkv",  # Cyrillic
        "映画_Movie.mkv",   # Japanese
        "Película_🎬.mkv",  # Spanish with emoji
        "Very_Long_Filename_That_Exceeds_Normal_Limits_And_Tests_System_Boundaries_Movie.mkv"
    ]


@pytest.fixture
def case_sensitive_filenames():
    """Case sensitivity test cases"""
    return [
        ("Movie.MKV", "movie.mkv"),
        ("SERIES.S01E01.mkv", "series.s01e01.mkv")
    ]


# Cleanup and validation helpers

@pytest.fixture(autouse=True)
def cleanup_temp_files():
    """Auto cleanup fixture that runs after each test"""
    yield
    # Cleanup any remaining temp files
    temp_dirs = []
    for temp_dir in temp_dirs:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def assert_helpers():
    """Helper assertion functions"""
    class AssertHelpers:
        @staticmethod
        def assert_file_in_database(state_store, file_path: str, **expected_fields):
            """Assert file exists in database with expected fields"""
            state_store.assert_file_exists(file_path, **expected_fields)
        
        @staticmethod
        def assert_metrics_match(actual: Dict[str, int], expected: Dict[str, int]):
            """Assert metrics match expected values"""
            from tests.fixtures import assert_metrics_equal
            assert_metrics_equal(actual, expected)
        
        @staticmethod
        def assert_no_due_files(state_store):
            """Assert no files are due for processing"""
            state_store.assert_no_due_files()
        
        @staticmethod
        def assert_processing_time_bounded(start_time: float, max_seconds: float):
            """Assert processing completed within time bound"""
            elapsed = time.time() - start_time
            assert elapsed < max_seconds, f"Processing took {elapsed}s, expected < {max_seconds}s"
    
    return AssertHelpers()


# Performance monitoring fixtures

@pytest.fixture
def performance_monitor():
    """Monitor test performance metrics"""
    class PerformanceMonitor:
        def __init__(self):
            self.start_time = None
            self.metrics = {}
        
        def start_timer(self, name: str):
            self.start_time = time.time()
        
        def end_timer(self, name: str):
            if self.start_time:
                self.metrics[name] = time.time() - self.start_time
                self.start_time = None
        
        def get_metric(self, name: str) -> float:
            return self.metrics.get(name, 0.0)
        
        def assert_under_limit(self, name: str, max_seconds: float):
            actual = self.get_metric(name)
            assert actual < max_seconds, f"{name} took {actual}s, expected < {max_seconds}s"
    
    return PerformanceMonitor()


# Configuration overrides for different test scenarios

@pytest.fixture
def quick_test_config():
    """Fast configuration for quick tests"""
    return create_test_config(
        stable_wait_sec=1,  # Faster stability
        batch_size=10,      # Larger batches
        loop_interval_sec=0.1,  # Faster loops
        integrity_quick_mode=True
    )


@pytest.fixture 
def stress_test_config():
    """Configuration for stress/performance tests"""
    return create_test_config(
        stable_wait_sec=5,
        batch_size=50,      # Large batches for stress testing
        max_state_entries=10000,  # Higher limits
        loop_interval_sec=1
    )