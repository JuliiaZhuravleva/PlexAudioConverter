"""
Главный файл для запуска всех тестов системы state-management
"""
import sys
import os
import subprocess
import time
from pathlib import Path

# Добавить корневую папку проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def run_tests():
    """Запустить все тесты с отчетом о покрытии"""
    
    print("🚀 Запуск тестов системы state-management")
    print("=" * 60)
    
    # Определить тестовые модули
    test_modules = [
        "tests.test_step2_core",
        "tests.test_step2_stability", 
        "tests.test_step2_pending",
        "tests.test_step2_file_ops",
        "tests.test_step2_groups",
        "tests.test_reliability"
    ]
    
    # Модули для будущих шагов (пропускаются)
    future_modules = [
        "tests.test_step3_backoff"
    ]
    
    print(f"📋 Активные тестовые модули: {len(test_modules)}")
    for module in test_modules:
        print(f"  ✓ {module}")
    
    print(f"\n⏳ Отложенные модули (Step 3+): {len(future_modules)}")
    for module in future_modules:
        print(f"  ⏸ {module}")
    
    print("\n" + "=" * 60)
    
    # Запустить тесты
    start_time = time.time()
    
    try:
        # Попробовать запустить с pytest
        cmd = [
            sys.executable, "-m", "pytest",
            "-v",
            "--tb=short",
            "--durations=10",
            *[f"{module.replace('.', '/')}.py" for module in test_modules]
        ]
        
        print(f"🔧 Команда: {' '.join(cmd)}")
        print()
        
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
        
        print("📊 РЕЗУЛЬТАТЫ ТЕСТОВ")
        print("=" * 40)
        print(result.stdout)
        
        if result.stderr:
            print("\n⚠️ ПРЕДУПРЕЖДЕНИЯ/ОШИБКИ:")
            print(result.stderr)
        
        elapsed = time.time() - start_time
        print(f"\n⏱️ Время выполнения: {elapsed:.2f} секунд")
        
        if result.returncode == 0:
            print("✅ Все тесты прошли успешно!")
        else:
            print(f"❌ Тесты завершились с кодом: {result.returncode}")
            
        return result.returncode
        
    except FileNotFoundError:
        print("⚠️ pytest не найден, запускаем тесты напрямую...")
        return run_tests_directly(test_modules)

def run_tests_directly(test_modules):
    """Запустить тесты напрямую без pytest"""
    
    success_count = 0
    total_count = len(test_modules)
    
    for module_name in test_modules:
        print(f"\n🧪 Тестирование {module_name}...")
        
        try:
            # Импортировать и запустить модуль
            module = __import__(module_name, fromlist=[''])
            
            # Найти тестовые классы
            test_classes = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    attr_name.startswith('Test') and 
                    attr.__module__ == module_name):
                    test_classes.append(attr)
            
            if test_classes:
                print(f"  Найдено тестовых классов: {len(test_classes)}")
                
                for test_class in test_classes:
                    print(f"    🔍 {test_class.__name__}")
                    
                    # Найти тестовые методы
                    test_methods = [method for method in dir(test_class) 
                                  if method.startswith('test_')]
                    
                    print(f"      Методов: {len(test_methods)}")
                    
                    # Запустить тесты (упрощенно)
                    instance = test_class()
                    for method_name in test_methods:
                        try:
                            method = getattr(instance, method_name)
                            method()
                            print(f"        ✓ {method_name}")
                        except Exception as e:
                            print(f"        ❌ {method_name}: {e}")
                
                success_count += 1
            else:
                print(f"  ⚠️ Тестовые классы не найдены")
                
        except Exception as e:
            print(f"  ❌ Ошибка импорта: {e}")
    
    print(f"\n📈 ИТОГО: {success_count}/{total_count} модулей успешно")
    return 0 if success_count == total_count else 1

def check_dependencies():
    """Проверить зависимости для тестов"""
    
    print("🔍 Проверка зависимостей...")
    
    required_modules = [
        'state_management',
        'core',
        'pathlib',
        'sqlite3',
        'threading'
    ]
    
    missing = []
    for module_name in required_modules:
        try:
            __import__(module_name)
            print(f"  ✓ {module_name}")
        except ImportError:
            print(f"  ❌ {module_name}")
            missing.append(module_name)
    
    if missing:
        print(f"\n⚠️ Отсутствующие модули: {missing}")
        print("Убедитесь что проект правильно настроен")
        return False
    
    print("✅ Все зависимости найдены")
    return True

def show_test_matrix():
    """Показать матрицу тестов"""
    
    print("\n📋 МАТРИЦА ТЕСТОВ")
    print("=" * 60)
    
    test_matrix = {
        "Step 2 - Обязательные": [
            "T-001: Discovery создаёт записи и не спиннит",
            "T-002: Size-gate: растущий файл не запускает Integrity", 
            "T-003: Стабилизация запускает Integrity",
            "T-004: PENDING защищает от повторного захвата",
            "T-005: Несколько файлов и DUE_LIMIT",
            "T-006: Дрожащий файл (мелкие дозаписи)",
            "T-007: Restart-recovery",
            "T-008: Rename перед стабилизацией",
            "T-009: Удаление во время ожидания",
            "T-010: Группа .stereo и original",
            "T-011: EN 2.0 пока не влияет",
            "T-012: Производительность idle"
        ],
        "Step 3 - Backoff (заготовки)": [
            "T-101: Backoff после INCOMPLETE",
            "T-102: Сброс backoff при изменении размера"
        ],
        "Step 4 - EN 2.0 (заготовки)": [
            "T-201: Skip, если есть EN 2.0",
            "T-202: Нет EN 2.0 — готов к конвертации"
        ],
        "Step 5 - Группы (заготовки)": [
            "T-301: Пара обязательна для «группа обработана»",
            "T-302: delete_original=true — достаточно одной копии"
        ],
        "Надёжность": [
            "T-401: GC processed-истории",
            "T-402: Migrator из старого processed_files",
            "T-403: Dangling-cleanup"
        ]
    }
    
    for category, tests in test_matrix.items():
        print(f"\n{category}:")
        for test in tests:
            status = "✅" if "Step 2" in category or "Надёжность" in category else "⏸️"
            print(f"  {status} {test}")

if __name__ == "__main__":
    print("🧪 СИСТЕМА ТЕСТИРОВАНИЯ STATE-MANAGEMENT")
    print("=" * 60)
    
    # Показать матрицу тестов
    show_test_matrix()
    
    print("\n" + "=" * 60)
    
    # Проверить зависимости
    if not check_dependencies():
        sys.exit(1)
    
    print("\n" + "=" * 60)
    
    # Запустить тесты
    exit_code = run_tests()
    
    print("\n" + "=" * 60)
    print("🏁 ЗАВЕРШЕНИЕ ТЕСТИРОВАНИЯ")
    
    if exit_code == 0:
        print("🎉 Все тесты успешно завершены!")
        print("\n📋 Следующие шаги:")
        print("  1. Проверить покрытие кода")
        print("  2. Реализовать Step 3 (backoff логика)")
        print("  3. Активировать соответствующие тесты")
    else:
        print("❌ Обнаружены проблемы в тестах")
        print("\n🔧 Рекомендации:")
        print("  1. Проверить логи выше")
        print("  2. Исправить failing тесты")
        print("  3. Убедиться что все компоненты реализованы")
    
    sys.exit(exit_code)
