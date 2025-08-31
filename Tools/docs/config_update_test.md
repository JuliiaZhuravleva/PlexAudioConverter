# ⚙️ Config Update Test

Инструмент для тестирования автоматического обновления конфигурационных файлов при добавлении новых секций и параметров в систему.

## 🎯 Назначение

- **Тестирование** механизма автообновления конфигурации
- **Проверка** совместимости старых и новых версий config.ini
- **Валидация** корректности миграции настроек
- **Отладка** проблем с конфигурацией

## 🔧 Функциональность

### Что тестируется
- Автоматическое добавление новых секций
- Добавление новых параметров в существующие секции
- Сохранение пользовательских настроек
- Корректность значений по умолчанию
- Обработка комментариев и форматирования

### Тестовые сценарии
1. **Старый конфиг без секции [Download]** - добавление новой секции
2. **Частично заполненная секция** - добавление недостающих параметров
3. **Поврежденный конфиг** - восстановление структуры
4. **Пустой файл** - создание конфигурации с нуля

## 🚀 Использование

### Запуск тестов
```bash
# Базовый тест
python config_update_test.py

# Подробный вывод
python config_update_test.py --verbose

# Тест конкретного файла
python config_update_test.py --config-path "path/to/test_config.ini"

# Сохранить результаты
python config_update_test.py --output-dir "/temp/config_tests"
```

### Параметры командной строки
- `--config-path PATH` - путь к тестовому конфигу
- `--output-dir DIR` - директория для результатов
- `--verbose` - подробный вывод
- `--clean` - очистить тестовые файлы после завершения
- `--backup` - создать резервные копии

## 📋 Процесс тестирования

### Этап 1: Подготовка
```
🔧 Создание тестовой среды
├─ Создание директории /temp/config_test/
├─ Генерация старого конфига (без новых секций)
└─ Подготовка эталонных данных
```

### Этап 2: Тестирование
```
🧪 Выполнение тестов
├─ Загрузка старого конфига через ConfigManager
├─ Автоматическое обновление структуры
├─ Проверка добавленных секций и параметров
└─ Валидация сохранности пользовательских настроек
```

### Этап 3: Валидация
```
✅ Проверка результатов
├─ Сравнение с эталонной структурой
├─ Проверка значений по умолчанию
├─ Тест загрузки обновленного конфига
└─ Генерация отчета
```

## 📊 Примеры тестовых случаев

### Тест 1: Добавление секции [Download]
**Исходный конфиг:**
```ini
[General]
watch_directory = E:\Download\Movie
check_interval = 300

[FFmpeg]
ffmpeg_path = ffmpeg
ffprobe_path = ffprobe
```

**Ожидаемый результат:**
```ini
[General]
watch_directory = E:\Download\Movie
check_interval = 300

[FFmpeg]
ffmpeg_path = ffmpeg
ffprobe_path = ffprobe

[Download]
enabled = true
check_interval = 5.0
stability_threshold = 30.0
notify_on_complete = true
cleanup_completed_hours = 24
```

### Тест 2: Добавление параметров в существующую секцию
**Исходная секция:**
```ini
[Telegram]
bot_token = your_bot_token_here
chat_id = your_chat_id_here
```

**После обновления:**
```ini
[Telegram]
bot_token = your_bot_token_here
chat_id = your_chat_id_here
enabled = true
send_conversion_reports = true
send_quality_alerts = true
```

## 🔍 Детали реализации

### Алгоритм тестирования
```python
def test_config_auto_update():
    """Основная функция тестирования"""
    
    # 1. Создание тестового окружения
    test_dir = Path("/temp/config_test")
    test_config = test_dir / "test_config.ini"
    
    # 2. Создание старого конфига
    create_old_config(test_config)
    
    # 3. Загрузка через ConfigManager (автообновление)
    config_manager = ConfigManager(config_path=test_config)
    
    # 4. Проверка результатов
    validate_updated_config(config_manager)
    
    # 5. Генерация отчета
    generate_test_report(test_results)
```

### Проверяемые аспекты
```python
def validate_updated_config(config_manager):
    """Валидация обновленной конфигурации"""
    
    # Проверка наличия новых секций
    assert config_manager.has_section('Download')
    assert config_manager.has_section('VideoIntegrity')
    
    # Проверка новых параметров
    assert config_manager.get('Download', 'enabled') == 'true'
    assert config_manager.get('Download', 'stability_threshold') == '30.0'
    
    # Проверка сохранности старых настроек
    assert config_manager.get('General', 'watch_directory') == original_value
```

## 📈 Отчеты и логирование

### Формат отчета
```json
{
  "test_timestamp": "2024-01-15T10:30:00",
  "test_duration": 2.5,
  "tests_run": 8,
  "tests_passed": 7,
  "tests_failed": 1,
  "results": [
    {
      "test_name": "add_download_section",
      "status": "PASSED",
      "duration": 0.3,
      "details": "Секция [Download] успешно добавлена"
    },
    {
      "test_name": "preserve_user_settings",
      "status": "FAILED",
      "duration": 0.2,
      "error": "Пользовательское значение watch_directory было перезаписано"
    }
  ]
}
```

### Логирование
```
2024-01-15 10:30:00 - INFO - Начало тестирования конфигурации
2024-01-15 10:30:00 - INFO - Создание тестового конфига: /temp/config_test/test_config.ini
2024-01-15 10:30:01 - INFO - ✅ Тест add_download_section: PASSED
2024-01-15 10:30:01 - ERROR - ❌ Тест preserve_user_settings: FAILED
2024-01-15 10:30:02 - INFO - Тестирование завершено: 7/8 тестов пройдено
```

## 🛠️ Кастомизация тестов

### Добавление новых тестов
```python
def test_custom_section():
    """Пользовательский тест"""
    
    # Создание тестового конфига
    config_content = """
    [General]
    watch_directory = /custom/path
    """
    
    # Тестирование
    config_manager = ConfigManager(config_content=config_content)
    
    # Проверки
    assert config_manager.has_section('CustomSection')
    assert config_manager.get('CustomSection', 'custom_param') == 'default_value'

# Регистрация теста
register_test('custom_section', test_custom_section)
```

### Конфигурация тестов
```python
TEST_CONFIG = {
    'test_timeout': 30,  # Таймаут для каждого теста
    'cleanup_on_success': True,  # Очистка при успехе
    'backup_original': True,  # Резервное копирование
    'verbose_output': False  # Подробный вывод
}
```

## 🚨 Устранение неполадок

### Частые проблемы

#### Тест не находит ConfigManager
```bash
# Проблема: модуль не в PYTHONPATH
# Решение: запуск из корневой директории проекта
cd "e:\My Projects\PlexAudioConverter"
python Tools/config_update_test.py
```

#### Ошибка доступа к /temp/
```bash
# Проблема: нет прав на создание файлов
# Решение: указать другую директорию
python config_update_test.py --output-dir "C:\Users\%USERNAME%\AppData\Local\Temp\config_test"
```

#### Конфиг не обновляется
```python
# Проверка версии ConfigManager
from core.config_manager import ConfigManager
print(ConfigManager.__version__)  # Должна быть >= 2.0

# Проверка наличия метода auto_update
assert hasattr(ConfigManager, 'auto_update_config')
```

### Отладка
```bash
# Запуск с максимальной детализацией
python config_update_test.py --verbose --debug

# Сохранение промежуточных файлов
python config_update_test.py --no-cleanup --output-dir "/temp/debug"

# Тест конкретного сценария
python config_update_test.py --test-only "add_download_section"
```

## 🔄 Интеграция в CI/CD

### GitHub Actions
```yaml
name: Config Update Tests
on: [push, pull_request]

jobs:
  config-tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run config tests
        run: python Tools/config_update_test.py --output-dir ./test-results
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: config-test-results
          path: ./test-results/
```

### Pre-commit hook
```bash
#!/bin/bash
# .git/hooks/pre-commit
echo "Запуск тестов конфигурации..."
python Tools/config_update_test.py --quick
if [ $? -ne 0 ]; then
    echo "❌ Тесты конфигурации не пройдены"
    exit 1
fi
echo "✅ Тесты конфигурации пройдены"
```

---

*Этот инструмент гарантирует стабильность системы конфигурации при добавлении новых функций и обновлениях.*
