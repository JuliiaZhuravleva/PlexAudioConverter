#!/usr/bin/env python3
"""
Metrics Tests
Тесты системы метрик
"""

import time
from ..metrics import init_metrics, get_metrics, MetricTimer


def test_metrics():
    """Тест метрик"""
    print("METRICS TEST: Система метрик")
    
    try:
        # Инициализируем метрики
        metrics = init_metrics(retention_hours=1, max_events=100)
        
        # Записываем несколько метрик
        metrics.increment("test_counter")
        metrics.gauge("test_gauge", 42.0)
        metrics.timing("test_timing", 123.45)
        
        # Проверяем счетчики
        counter_value = metrics.get_counter("test_counter")
        print(f"   Test counter: {counter_value}")
        assert counter_value == 1.0, f"Ожидали 1.0, получили {counter_value}"
        
        # Проверяем сводку
        summary = metrics.get_summary(since_hours=1)
        print(f"   Всего событий: {summary['total_events']}")
        print(f"   Метрик: {len(summary['metrics'])}")
        
        # Тест контекстного менеджера
        with MetricTimer("test_timer"):
            time.sleep(0.01)  # 10мс
        
        # Проверяем что метрика записалась
        timer_events = metrics.get_events("test_timer_duration_ms")
        print(f"   Timer событий: {len(timer_events)}")
        
        print("   OK: Метрики работают")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metric_timer():
    """Тест MetricTimer"""
    print("\nTIMER TEST: MetricTimer контекстный менеджер")
    
    try:
        metrics = get_metrics()
        
        # Тест успешного выполнения
        with MetricTimer("test_success"):
            time.sleep(0.005)  # 5мс
        
        # Проверяем что записались метрики
        success_events = metrics.get_events("test_success_success")
        duration_events = metrics.get_events("test_success_duration_ms")
        
        print(f"   Success событий: {len(success_events)}")
        print(f"   Duration событий: {len(duration_events)}")
        
        assert len(success_events) > 0, "Не записано success событие"
        assert len(duration_events) > 0, "Не записано duration событие"
        
        # Проверяем время
        if duration_events:
            duration = duration_events[0].value
            print(f"   Длительность: {duration:.2f}мс")
            assert duration > 0, "Длительность должна быть положительной"
        
        # Тест с исключением
        try:
            with MetricTimer("test_error"):
                raise ValueError("Test error")
        except ValueError:
            pass  # ожидаемое исключение
        
        # Проверяем что записалась error метрика
        error_events = metrics.get_events("test_error_error")
        print(f"   Error событий: {len(error_events)}")
        
        assert len(error_events) > 0, "Не записано error событие"
        
        print("   OK: MetricTimer работает корректно")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metrics_aggregation():
    """Тест агрегации метрик"""
    print("\nAGGREGATION TEST: Агрегация метрик")
    
    try:
        metrics = get_metrics()
        
        # Записываем серию метрик
        for i in range(10):
            metrics.gauge("test_series", float(i))
        
        # Проверяем агрегацию
        count = metrics.get_aggregate("test_series", "count", since_hours=1)
        sum_val = metrics.get_aggregate("test_series", "sum", since_hours=1) 
        avg_val = metrics.get_aggregate("test_series", "avg", since_hours=1)
        min_val = metrics.get_aggregate("test_series", "min", since_hours=1)
        max_val = metrics.get_aggregate("test_series", "max", since_hours=1)
        
        print(f"   Count: {count}")
        print(f"   Sum: {sum_val}")
        print(f"   Average: {avg_val}")
        print(f"   Min: {min_val}")
        print(f"   Max: {max_val}")
        
        # Проверяем правильность вычислений
        assert count == 10, f"Count должно быть 10, получили {count}"
        assert sum_val == 45, f"Sum должно быть 45, получили {sum_val}"  # 0+1+2+...+9 = 45
        assert avg_val == 4.5, f"Average должно быть 4.5, получили {avg_val}"
        assert min_val == 0, f"Min должно быть 0, получили {min_val}"
        assert max_val == 9, f"Max должно быть 9, получили {max_val}"
        
        print("   OK: Агрегация работает корректно")
        return True
        
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_metrics_tests():
    """Запуск тестов метрик"""
    print("=== ТЕСТИРОВАНИЕ СИСТЕМЫ МЕТРИК ===")
    
    tests = [
        ("Базовые метрики", test_metrics),
        ("MetricTimer", test_metric_timer),
        ("Агрегация метрик", test_metrics_aggregation)
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
    success = run_metrics_tests()
    exit(0 if success else 1)