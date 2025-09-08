"""
Базовый тест для проверки работоспособности тестовой среды
"""
import sys
import os
from pathlib import Path

# Добавить корневую папку в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_imports():
    """Тест импорта основных модулей"""
    from state_management.enums import IntegrityStatus, ProcessedStatus
    from state_management.store import StateStore
    from state_management.config import StateConfig
    
    # Assert that the imports worked (they would raise ImportError if not)
    assert IntegrityStatus.UNKNOWN is not None
    assert ProcessedStatus.NEW is not None
    assert StateStore is not None
    assert StateConfig is not None

def test_fixtures():
    """Тест импорта тестовых утилит"""
    from tests.fixtures import (
        TempFS, SyntheticDownloader, FakeClock, FakeIntegrityChecker, FFprobeStub,
        StateStoreFixture, StatePlannerFixture, TEST_CONSTANTS, create_test_config,
        create_sample_video_file, assert_metrics_equal
    )
    
    # Assert that the fixture imports worked
    assert TempFS is not None
    assert FakeClock is not None
    assert TEST_CONSTANTS is not None

def test_temp_fs():
    """Тест TempFS"""
    from tests.fixtures import TempFS
    
    with TempFS() as temp_dir:
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello, World!")
        
        assert test_file.exists()
        assert test_file.read_text() == "Hello, World!"

def test_state_store():
    """Тест StateStoreFixture"""
    from tests.fixtures import StateStoreFixture
    from state_management.enums import IntegrityStatus, ProcessedStatus
    
    with StateStoreFixture() as test_store:
        # Проверить создание базы
        assert test_store.get_file_count() == 0
        
        # Добавить файл
        test_store.store.upsert_file(
            path="/test/file.mkv",
            size_bytes=1024*1024,
            mtime=1234567890,
            integrity_status=IntegrityStatus.UNKNOWN,
            processed_status=ProcessedStatus.NEW
        )
        
        assert test_store.get_file_count() == 1

def test_fake_integrity_checker():
    """Тест FakeIntegrityChecker"""
    from tests.fixtures import FakeIntegrityChecker
    from state_management.enums import IntegrityStatus
    
    checker = FakeIntegrityChecker()
    checker.delay_seconds = 0  # Без задержки для теста
    
    status, score, mode = checker.check_video_integrity("/fake/file.mkv")
    
    assert status == IntegrityStatus.COMPLETE
    assert score == 1.0
    assert mode == "quick"
    assert checker.call_count == 1

def run_basic_tests():
    """Запустить все базовые тесты"""
    print("🧪 БАЗОВЫЕ ТЕСТЫ ТЕСТОВОЙ СРЕДЫ")
    print("=" * 50)
    
    tests = [
        ("Импорт основных модулей", test_imports),
        ("Импорт тестовых утилит", test_fixtures),
        ("TempFS", test_temp_fs),
        ("TestStateStore", test_state_store),
        ("FakeIntegrityChecker", test_fake_integrity_checker)
    ]
    
    passed = 0
    total = len(tests)
    
    for name, test_func in tests:
        print(f"\n🔍 {name}...")
        try:
            if test_func():
                passed += 1
            else:
                print(f"❌ {name} не прошел")
        except Exception as e:
            print(f"❌ {name} упал с ошибкой: {e}")
    
    print(f"\n📊 РЕЗУЛЬТАТ: {passed}/{total} тестов прошли")
    
    if passed == total:
        print("🎉 Все базовые тесты успешны! Тестовая среда готова.")
        return True
    else:
        print("⚠️ Есть проблемы с тестовой средой. Нужно исправить.")
        return False

if __name__ == "__main__":
    success = run_basic_tests()
    sys.exit(0 if success else 1)
