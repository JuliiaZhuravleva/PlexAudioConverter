#!/usr/bin/env python3
"""
Test Runner
Запуск всех тестов системы управления состояниями
"""

import asyncio
import sys
from pathlib import Path

# Добавляем пути для импортов
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from .test_basic import run_basic_tests
from .test_performance import run_performance_tests
from .test_metrics import run_metrics_tests
from .test_integrity import run_integrity_tests


async def run_all_tests():
    """Запуск всех тестов"""
    print("=" * 60)
    print("STATE MANAGEMENT - ПОЛНЫЙ НАБОР ТЕСТОВ")
    print("=" * 60)
    
    test_suites = [
        ("Базовые тесты", run_basic_tests),
        ("Тесты производительности", run_performance_tests), 
        ("Тесты метрик", run_metrics_tests),
        ("Тесты целостности", run_integrity_tests)
    ]
    
    total_passed = 0
    total_failed = 0
    
    for suite_name, test_func in test_suites:
        print(f"\n{suite_name}:")
        print("-" * len(suite_name + ":"))
        
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            
            if result:
                total_passed += 1
                print(f"OK {suite_name}: PASSED")
            else:
                total_failed += 1
                print(f"FAIL {suite_name}: FAILED")
                
        except Exception as e:
            total_failed += 1
            print(f"ERROR {suite_name}: ERROR - {e}")
    
    # Итоговый отчет
    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 60)
    print(f"Наборов тестов пройдено: {total_passed}")
    print(f"Наборов тестов не прошло: {total_failed}")
    
    if total_failed == 0:
        print("SUCCESS: ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        return True
    else:
        print("WARNING: ЕСТЬ ПРОБЛЕМЫ, ТРЕБУЮЩИЕ ВНИМАНИЯ")
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nТестирование прервано пользователем")
        exit(1)