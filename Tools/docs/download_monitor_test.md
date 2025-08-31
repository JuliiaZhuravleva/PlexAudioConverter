# 📥 Download Monitor Test

Инструмент для тестирования системы мониторинга загрузок торрент-файлов. Создает тестовые сценарии для проверки детекции завершения загрузки различными методами.

## 🎯 Назначение

- **Тестирование** алгоритмов детекции завершения загрузки
- **Проверка** работы с различными торрент-клиентами
- **Валидация** системы уведомлений о статусе файлов
- **Отладка** проблем с мониторингом загрузок

## 🔧 Функциональность

### Тестируемые сценарии
- Файлы с временными расширениями (.part, .!ut, .!qb)
- Мониторинг стабильности размера файла
- Детекция блокировки файлов процессами
- Проверка времени модификации
- Обработка различных статусов загрузки

### Поддерживаемые торрент-клиенты
- **uTorrent** - расширения .!ut
- **qBittorrent** - расширения .!qb
- **Transmission/Deluge** - расширения .part
- **Общие форматы** - .tmp, .download, .incomplete

## 🚀 Использование

### Базовый запуск
```bash
# Простой тест
python download_monitor_test.py

# Тест с кастомной директорией
python download_monitor_test.py --test-dir "/temp/download_test"

# Ускоренный тест (короткие интервалы)
python download_monitor_test.py --quick

# Подробный вывод
python download_monitor_test.py --verbose
```

### Параметры командной строки
- `--test-dir DIR` - директория для тестовых файлов
- `--quick` - ускоренный режим (5 сек стабильности)
- `--verbose` - подробное логирование
- `--no-cleanup` - не удалять тестовые файлы
- `--stability-time SEC` - время стабильности для тестов
- `--client TYPE` - тест конкретного клиента (utorrent, qbittorrent, transmission)

## 📋 Тестовые сценарии

### Сценарий 1: Файл с расширением .part
```
📁 Создание: movie1.mkv.part (50 МБ)
⏱️ Симуляция загрузки: увеличение размера
📊 Мониторинг: детекция роста файла
✅ Переименование: movie1.mkv.part → movie1.mkv
🎯 Ожидаемый результат: DOWNLOADING → COMPLETED
```

### Сценарий 2: uTorrent файл (.!ut)
```
📁 Создание: movie2.mp4.!ut (75 МБ)
⏱️ Симуляция: периодическое изменение размера
📊 Мониторинг: детекция нестабильности
✅ Удаление расширения: movie2.mp4.!ut → movie2.mp4
🎯 Ожидаемый результат: DOWNLOADING → COMPLETED
```

### Сценарий 3: Стабильный файл
```
📁 Создание: movie3.avi (100 МБ)
⏱️ Без изменений: размер остается постоянным
📊 Мониторинг: детекция стабильности
🎯 Ожидаемый результат: UNKNOWN → COMPLETED
```

### Сценарий 4: Заблокированный файл
```
📁 Создание: movie4.mkv (80 МБ)
🔒 Блокировка: открытие файла на запись
📊 Мониторинг: детекция блокировки
🔓 Разблокировка: закрытие файла
🎯 Ожидаемый результат: DOWNLOADING → COMPLETED
```

## 🔍 Детали реализации

### Класс DownloadMonitorTester
```python
class DownloadMonitorTester:
    def __init__(self, test_dir="/temp/download_test"):
        self.test_dir = Path(test_dir)
        self.monitor = DownloadMonitor(stability_threshold=5.0)
        self.monitor.add_callback(self._on_status_change)
        
    def _on_status_change(self, file_info):
        """Обработчик изменения статуса"""
        print(f"📊 {file_info.file_path.name} -> {file_info.status.value}")
        print(f"   Метод: {file_info.detection_method}")
        print(f"   Размер: {file_info.size / (1024*1024):.1f} МБ")
```

### Методы тестирования
```python
def test_part_file_scenario(self):
    """Тест файла с расширением .part"""
    
    # Создание файла .part
    part_file = self.test_dir / "movie.mkv.part"
    self._create_file(part_file, 50 * 1024 * 1024)
    
    # Добавление в мониторинг
    self.monitor.add_file(part_file)
    
    # Симуляция загрузки
    await self._simulate_download(part_file)
    
    # Переименование в финальный файл
    final_file = part_file.with_suffix('')
    part_file.rename(final_file)
    
    # Проверка статуса
    assert self.monitor.get_status(final_file) == DownloadStatus.COMPLETED
```

## 📊 Результаты тестирования

### Формат отчета
```
=== Результаты тестирования мониторинга загрузок ===

📁 Тестовая директория: /temp/download_test
⏱️ Время стабильности: 5.0 секунд
🔄 Интервал проверки: 1.0 секунд

Тест 1: Файл .part
├─ Статус: ✅ ПРОЙДЕН
├─ Время: 12.3 сек
├─ Детекция: extension_based
└─ Переходы: DOWNLOADING → COMPLETED

Тест 2: uTorrent файл (.!ut)
├─ Статус: ✅ ПРОЙДЕН
├─ Время: 8.7 сек
├─ Детекция: extension_based
└─ Переходы: DOWNLOADING → COMPLETED

Тест 3: Стабильный файл
├─ Статус: ✅ ПРОЙДЕН
├─ Время: 6.2 сек
├─ Детекция: stability_based
└─ Переходы: UNKNOWN → COMPLETED

Тест 4: Заблокированный файл
├─ Статус: ⚠️ ЧАСТИЧНО
├─ Время: 15.1 сек
├─ Детекция: lock_based
└─ Переходы: DOWNLOADING → COMPLETED (с задержкой)

📊 Общий результат: 4/4 теста пройдено
⏱️ Общее время: 42.3 секунды
```

### JSON отчет
```json
{
  "test_session": {
    "timestamp": "2024-01-15T10:30:00",
    "duration": 42.3,
    "test_dir": "/temp/download_test",
    "stability_threshold": 5.0
  },
  "tests": [
    {
      "name": "part_file_scenario",
      "status": "PASSED",
      "duration": 12.3,
      "file": "movie1.mkv.part",
      "detection_method": "extension_based",
      "status_transitions": ["DOWNLOADING", "COMPLETED"]
    }
  ],
  "summary": {
    "total_tests": 4,
    "passed": 4,
    "failed": 0,
    "success_rate": 100.0
  }
}
```

## 🛠️ Расширенные возможности

### Кастомные сценарии
```python
def create_custom_scenario(self, scenario_config):
    """Создание пользовательского сценария"""
    
    file_path = self.test_dir / scenario_config['filename']
    
    # Создание файла с заданными параметрами
    self._create_file(file_path, scenario_config['initial_size'])
    
    # Применение сценария
    for step in scenario_config['steps']:
        await self._apply_step(file_path, step)
        
    return self._validate_result(file_path, scenario_config['expected'])
```

### Конфигурация сценариев
```yaml
scenarios:
  - name: "slow_download"
    filename: "slow_movie.mkv.part"
    initial_size: 10MB
    steps:
      - action: "grow"
        size: "5MB"
        delay: 2
      - action: "pause"
        duration: 10
      - action: "grow" 
        size: "15MB"
        delay: 1
      - action: "complete"
    expected: "COMPLETED"
```

### Стресс-тестирование
```python
def stress_test(self, num_files=100):
    """Стресс-тест с множественными файлами"""
    
    files = []
    for i in range(num_files):
        file_path = self.test_dir / f"stress_test_{i}.mkv.part"
        self._create_file(file_path, random.randint(10, 100) * 1024 * 1024)
        files.append(file_path)
        
    # Добавление всех файлов в мониторинг
    for file_path in files:
        self.monitor.add_file(file_path)
        
    # Симуляция одновременных изменений
    await asyncio.gather(*[
        self._simulate_random_download(f) for f in files
    ])
    
    # Проверка результатов
    return self._validate_stress_results(files)
```

## 🚨 Устранение неполадок

### Частые проблемы

#### Тесты не запускаются
```bash
# Проверка зависимостей
python -c "from core.download_monitor import DownloadMonitor; print('OK')"

# Проверка прав доступа
python -c "from pathlib import Path; Path('/temp/test').mkdir(parents=True, exist_ok=True); print('OK')"
```

#### Ложные срабатывания
```python
# Увеличение времени стабильности
python download_monitor_test.py --stability-time 10

# Отключение быстрых тестов
python download_monitor_test.py --no-quick
```

#### Файлы не удаляются
```bash
# Принудительная очистка
python download_monitor_test.py --force-cleanup

# Ручная очистка
rm -rf /temp/download_test/*
```

### Отладка
```bash
# Максимальная детализация
python download_monitor_test.py --verbose --debug

# Сохранение логов
python download_monitor_test.py --log-file "/temp/download_test.log"

# Тест конкретного сценария
python download_monitor_test.py --scenario "part_file_only"
```

## 🔄 Интеграция в тестирование

### Автоматические тесты
```python
import unittest

class TestDownloadMonitor(unittest.TestCase):
    def setUp(self):
        self.tester = DownloadMonitorTester("/temp/unittest")
        
    def test_part_file_detection(self):
        result = self.tester.test_part_file_scenario()
        self.assertTrue(result.success)
        self.assertEqual(result.final_status, DownloadStatus.COMPLETED)
        
    def tearDown(self):
        self.tester.cleanup()
```

### Continuous Integration
```yaml
# .github/workflows/download-monitor-tests.yml
name: Download Monitor Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Run download monitor tests
        run: |
          python Tools/download_monitor_test.py --quick --json > test_results.json
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: download-monitor-results
          path: test_results.json
```

---

*Этот инструмент обеспечивает надежность системы мониторинга загрузок и помогает выявить проблемы до их появления в продакшене.*
