# State Management System

Система управления состояниями файлов для Plex Audio Converter. Обеспечивает детерминизм, минимальные холостые проверки и предсказуемые переходы состояний.

## Основные компоненты

### StateManager
Главный API для работы со всей системой управления состояниями.

```python
from state_management import create_state_manager

# Создание менеджера
manager = create_state_manager(environment='development')

# Сканирование директории
result = await manager.discover_directory("/path/to/videos")

# Обработка ожидающих файлов
processed = await manager.process_pending()

# Получение статуса системы
status = manager.get_system_status()
```

### AudioStateMachine
Конечный автомат для управления жизненным циклом файлов.

### StateStore
SQLite-хранилище состояний с транзакциями и индексацией.

### StatePlanner
Планировщик задач на основе `next_check_at`.

## Состояния файлов

### IntegrityStatus
- `UNKNOWN` - не проверено
- `PENDING` - проверка идет
- `COMPLETE` - целостность подтверждена
- `INCOMPLETE` - проверка не прошла
- `ERROR` - ошибка проверки

### ProcessedStatus
- `NEW` - новый файл
- `SKIPPED_HAS_EN2` - есть английская 2.0 дорожка
- `CONVERTED` - сконвертирован
- `GROUP_PROCESSED` - группа обработана
- `IGNORED` - исключен
- `DUPLICATE` - дубликат

## Workflow

```
NEW → SIZE_CHANGING → WAIT_STABLE → INTEGRITY_PENDING → 
INTEGRITY_COMPLETE → CHECK_AUDIO → SKIP_EN2/READY_FOR_CONVERSION → 
GROUP_UPDATE → GROUP_PROCESSED
```

## Конфигурация

```python
from state_management.config import StateConfig

config = StateConfig(
    stable_wait_sec=30,      # время стабильности файла
    backoff_step_sec=30,     # шаг backoff при ошибках
    batch_size=50,           # размер пакета для обработки
    integrity_quick_mode=True # быстрая проверка целостности
)
```

## Метрики

```python
from state_management import get_metrics

metrics = get_metrics()
summary = metrics.get_summary(since_hours=1.0)
print(f"Обработано файлов: {summary['counters']['files_discovered']}")
```

## Запуск

### Программно
```python
import asyncio
from state_management import create_state_manager

async def main():
    manager = create_state_manager()
    await manager.discover_directory("/path/to/videos")
    await manager.start_monitoring()  # бесконечный цикл

asyncio.run(main())
```

### CLI
```bash
# Сканирование директории
python -m state_management.manager --scan /path/to/videos

# Запуск мониторинга
python -m state_management.manager --monitor

# Статус системы
python -m state_management.manager --status

# Обслуживание
python -m state_management.manager --maintenance
```

## Тестирование

```bash
cd state_management
python -m pytest tests/ -v
```

## Архитектура

- **Enums** - перечисления состояний с валидацией переходов
- **Models** - модели данных (FileEntry, GroupEntry) с бизнес-логикой  
- **Store** - SQLite хранилище с индексами и транзакциями
- **Planner** - планировщик на основе `next_check_at` 
- **Machine** - конечный автомат с обработчиками событий
- **Manager** - единое API для всех операций
- **Config** - централизованная конфигурация
- **Metrics** - сбор метрик и телеметрии

## Производительность

- Индексированные запросы по `next_check_at`
- Пакетная обработка файлов
- Backoff при ошибках
- GC старых записей
- Connection pooling для SQLite