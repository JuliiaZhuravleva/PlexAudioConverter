# State Management Tests

Тесты для системы управления состояниями PlexAudioConverter.

## Структура тестов

### `test_basic.py`
Базовые тесты жизненного цикла файлов:
- Обнаружение и стабилизация файлов
- Сброс состояний при изменении размера
- Основные операции state machine

### `test_performance.py`
Тесты производительности:
- Нагрузочное тестирование БД (5000+ записей)
- Производительность запросов get_due_files
- Операции CRUD для StateStore
- Проверка индексов БД

### `test_metrics.py`
Тесты системы метрик:
- Базовые операции (increment, gauge, timing)
- MetricTimer контекстный менеджер
- Агрегация и сводные данные

### `test_integrity.py`
Тесты системы проверки целостности:
- IntegrityAdapter API
- Проверка QUICK vs FULL режимов
- Обработка ошибок

### `run_all.py`
Главный test runner для запуска всех тестовых наборов.

## Запуск тестов

### Отдельные наборы тестов:
```bash
# Базовые тесты
python -m state_management.tests.test_basic

# Тесты производительности
python -m state_management.tests.test_performance

# Тесты метрик
python -m state_management.tests.test_metrics

# Тесты целостности
python -m state_management.tests.test_integrity
```

### Все тесты сразу:
```bash
python -m state_management.tests.run_all
```

## Требования к окружению

- Python 3.8+
- SQLite3 (встроен в Python)
- Временные директории для тестовых файлов

## Известные ограничения

- Тесты IntegrityAdapter требуют ffmpeg для полной функциональности
- Windows Service тесты требуют win32serviceutil (не критично)
- Некоторые тесты создают временные файлы и БД

## Результаты тестирования

При успешном прохождении ожидается:
- ✅ Тесты производительности: PASSED
- ✅ Тесты метрик: PASSED  
- ✅ Тесты целостности: PASSED
- ❌ Базовые тесты: частично (из-за win32 зависимостей)

Критичные компоненты (StateStore, Metrics, Planner) проходят все тесты.