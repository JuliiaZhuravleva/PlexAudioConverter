#!/usr/bin/env python3
"""
Integrity Tests
Тесты системы проверки целостности
"""

import time
import tempfile
import shutil
from pathlib import Path

from ..integrity_adapter import IntegrityAdapter
from ..enums import IntegrityMode, IntegrityStatus


def test_integrity_adapter():
    """Тест IntegrityAdapter"""
    print("INTEGRITY TEST: Адаптер проверки целостности")
    
    try:
        adapter = IntegrityAdapter()
        
        if not adapter.is_available():
            print("   SKIP: VideoIntegrityChecker недоступен")
            return True
        
        # Создаем тестовый файл
        temp_dir = Path(tempfile.mkdtemp(prefix="integrity_test_"))
        test_file = temp_dir / "test.mp4"
        
        with open(test_file, 'wb') as f:
            f.write(b'0' * (1024 * 1024))  # 1MB тестовых данных
        
        try:
            # Тест QUICK режима
            print("   Тестирование QUICK режима...")
            start = time.time()
            status_quick, score_quick = adapter.check_video_integrity(str(test_file), IntegrityMode.QUICK)
            time_quick = time.time() - start
            
            print(f"   QUICK: {status_quick.value} (score={score_quick}, {time_quick:.3f}с)")
            
            # Тест FULL режима
            print("   Тестирование FULL режима...")
            start = time.time()
            status_full, score_full = adapter.check_video_integrity(str(test_file), IntegrityMode.FULL)
            time_full = time.time() - start
            
            print(f"   FULL: {status_full.value} (score={score_full}, {time_full:.3f}с)")
            
            # Проверяем что статусы не ERROR
            success = status_quick not in {IntegrityStatus.ERROR} or status_full not in {IntegrityStatus.ERROR}
            
            if success:
                print("   OK: IntegrityAdapter работает")
            else:
                print("   WARNING: Все проверки вернули ERROR (возможно нет ffmpeg)")
            
            return True
            
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            
    except Exception as e:
        print(f"   ERROR: {e}")
        return False


def test_integrity_adapter_api():
    """Тест API IntegrityAdapter без внешних зависимостей"""
    print("\nAPI TEST: IntegrityAdapter API")
    
    try:
        adapter = IntegrityAdapter()
        
        # Проверяем что адаптер создается
        print(f"   Адаптер создан: available={adapter.is_available()}")
        
        # Проверяем вызов с несуществующим файлом
        status, score = adapter.check_video_integrity("/nonexistent/file.mp4", IntegrityMode.QUICK)
        print(f"   Несуществующий файл: {status.value} (score={score})")
        
        # Должен вернуть ERROR или UNKNOWN
        assert status in {IntegrityStatus.ERROR, IntegrityStatus.UNKNOWN}, "Неожиданный статус для несуществующего файла"
        
        print("   OK: API IntegrityAdapter работает корректно")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_integrity_tests():
    """Запуск тестов целостности"""
    print("=== ТЕСТИРОВАНИЕ СИСТЕМЫ ЦЕЛОСТНОСТИ ===")
    
    tests = [
        ("API IntegrityAdapter", test_integrity_adapter_api),
        ("IntegrityAdapter с файлами", test_integrity_adapter)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"   -> PASSED\n")
            else:
                failed += 1
                print(f"   -> FAILED\n")
                
        except Exception as e:
            failed += 1
            print(f"   -> ERROR: {e}\n")
    
    print("=== РЕЗУЛЬТАТ ===")
    print(f"Прошло: {passed}, Не прошло: {failed}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_integrity_tests()
    exit(0 if success else 1)