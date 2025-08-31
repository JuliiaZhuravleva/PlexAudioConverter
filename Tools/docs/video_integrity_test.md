# 🎬 Video Integrity Test

Инструмент для тестирования системы проверки целостности видеофайлов с использованием FFmpeg/FFprobe. Позволяет выявлять неполные, поврежденные или некорректно загруженные видеофайлы.

## 🎯 Назначение

- **Тестирование** алгоритмов детекции целостности видео
- **Проверка** работы с различными видеоформатами
- **Валидация** точности определения статуса файлов
- **Отладка** проблем с FFmpeg анализом

## 🔧 Функциональность

### Методы детекции FFmpeg
- **Анализ метаданных** - проверка длительности и количества кадров
- **Тест читаемости** - декодирование от начала до конца
- **Проверка участков** - тестирование начала, середины и конца
- **Бинарный поиск** - определение последней читаемой секунды
- **Расчет коэффициента** - соотношение читаемой/заявленной длительности

### Статусы целостности
- **COMPLETE** - файл полностью читается
- **INCOMPLETE** - файл обрывается или неполный
- **CORRUPTED** - серьезные повреждения данных
- **UNREADABLE** - не удается прочитать метаданные
- **UNKNOWN** - статус неопределен

## 🚀 Использование

### Базовый запуск
```bash
# Тест системы целостности
python video_integrity_test.py

# Тест конкретного файла
python video_integrity_test.py --file "path/to/video.mkv"

# Пакетный тест директории
python video_integrity_test.py --directory "E:\Download\Movie"

# Подробный вывод
python video_integrity_test.py --verbose
```

### Параметры командной строки
- `--file PATH` - проверить конкретный файл
- `--directory DIR` - пакетная проверка директории
- `--formats EXT1,EXT2` - фильтр по расширениям
- `--verbose` - подробное логирование
- `--json` - вывод в JSON формате
- `--output-dir DIR` - директория для отчетов
- `--timeout SEC` - таймаут для FFmpeg операций

## 📋 Поддерживаемые форматы

### Основные форматы
- **.mkv** - Matroska Video
- **.mp4** - MPEG-4 Part 14
- **.avi** - Audio Video Interleave
- **.mov** - QuickTime Movie
- **.wmv** - Windows Media Video
- **.flv** - Flash Video
- **.m4v** - iTunes Video
- **.webm** - WebM Video

### Алгоритм проверки
```
1. Быстрая проверка метаданных
   ├─ Извлечение длительности
   ├─ Подсчет кадров
   └─ Проверка основных потоков

2. Тест декодирования начала
   ├─ Декодирование первых 10 секунд
   └─ Проверка на ошибки

3. Проверка середины и конца
   ├─ Тест средней части файла
   ├─ Проверка последних 10 секунд
   └─ Бинарный поиск проблемных участков

4. Расчет коэффициента читаемости
   ├─ Соотношение читаемой/заявленной длительности
   └─ Определение финального статуса

5. Fallback на проверку заголовков
   └─ При ошибках FFmpeg
```

## 🔍 Детали реализации

### Класс VideoIntegrityChecker
```python
from core.video_integrity_checker import VideoIntegrityChecker, VideoIntegrityStatus

def test_video_integrity():
    """Основная функция тестирования"""
    
    checker = VideoIntegrityChecker()
    
    test_files = [
        Path("complete_video.mkv"),
        Path("incomplete_download.mp4"),
        Path("corrupted_file.avi")
    ]
    
    for file_path in test_files:
        if file_path.exists():
            status = checker.check_integrity(file_path)
            print(f"{file_path.name}: {status.value}")
```

### Методы проверки
```python
def check_file_integrity(self, file_path):
    """Комплексная проверка файла"""
    
    # 1. Проверка метаданных
    metadata = self._get_video_metadata(file_path)
    if not metadata:
        return VideoIntegrityStatus.UNREADABLE
    
    # 2. Тест декодирования
    decode_result = self._test_decode_segments(file_path, metadata)
    
    # 3. Расчет коэффициента читаемости
    readability_ratio = decode_result.readable_duration / metadata.total_duration
    
    # 4. Определение статуса
    return self._determine_status(readability_ratio, decode_result)
```

## 📊 Результаты тестирования

### Консольный вывод
```
=== Тест системы проверки целостности видеофайлов ===

Проверка файла: TWD.[S07E04].HD1080.DD5.1.LostFilm.mkv
Путь: E:/Download/Movie/TWD (Season 07) LOST 1080/TWD.[S07E04].HD1080.DD5.1.LostFilm.mkv
Существует: True
Размер: 1847.3 MB

📊 Анализ целостности:
├─ Метаданные: ✅ Читаются
├─ Длительность: 42:15 (2535 секунд)
├─ Видеопоток: H.264, 1920x1080, 23.976 fps
├─ Аудиопоток: AC-3, 5.1 каналов, 640 kbps

🔍 Тест декодирования:
├─ Начало (0-10с): ✅ OK
├─ Середина (1267с): ✅ OK  
├─ Конец (2525-2535с): ✅ OK
├─ Читаемая длительность: 2535/2535 секунд (100.0%)

✅ Статус: COMPLETE
   Файл полностью читается и готов к обработке
```

### JSON отчет
```json
{
  "file_path": "TWD.[S07E04].HD1080.DD5.1.LostFilm.mkv",
  "file_size": 1937891328,
  "timestamp": "2024-01-15T10:30:00",
  "integrity_check": {
    "status": "COMPLETE",
    "confidence": 1.0,
    "metadata": {
      "duration": 2535.0,
      "video_codec": "h264",
      "resolution": "1920x1080",
      "fps": 23.976,
      "audio_codec": "ac3",
      "channels": 6
    },
    "decode_test": {
      "segments_tested": 3,
      "segments_passed": 3,
      "readable_duration": 2535.0,
      "readability_ratio": 1.0,
      "errors": []
    }
  }
}
```

## 🛠️ Расширенные возможности

### Кастомные тестовые файлы
```python
def create_test_scenarios():
    """Создание тестовых сценариев"""
    
    scenarios = [
        {
            'name': 'complete_file',
            'description': 'Полностью загруженный файл',
            'expected_status': VideoIntegrityStatus.COMPLETE
        },
        {
            'name': 'truncated_file', 
            'description': 'Обрезанный файл (50% от оригинала)',
            'expected_status': VideoIntegrityStatus.INCOMPLETE
        },
        {
            'name': 'corrupted_header',
            'description': 'Поврежденный заголовок файла',
            'expected_status': VideoIntegrityStatus.CORRUPTED
        }
    ]
    
    return scenarios
```

### Пакетное тестирование
```python
def batch_integrity_test(directory, formats=None):
    """Пакетная проверка директории"""
    
    if formats is None:
        formats = ['.mkv', '.mp4', '.avi', '.mov']
    
    checker = VideoIntegrityChecker()
    results = []
    
    for file_path in Path(directory).rglob('*'):
        if file_path.suffix.lower() in formats:
            status = checker.check_integrity(file_path)
            results.append({
                'file': str(file_path),
                'status': status.value,
                'size': file_path.stat().st_size
            })
    
    return results
```

### Интеграция с мониторингом загрузок
```python
def integrate_with_download_monitor():
    """Интеграция с системой мониторинга"""
    
    from core.download_monitor import DownloadMonitor
    
    def on_download_complete(file_info):
        """Callback при завершении загрузки"""
        
        if file_info.file_path.suffix.lower() in VIDEO_EXTENSIONS:
            checker = VideoIntegrityChecker()
            status = checker.check_integrity(file_info.file_path)
            
            if status != VideoIntegrityStatus.COMPLETE:
                logger.warning(f"⚠️ Проблема с целостностью: {file_info.file_path}")
                # Отправить уведомление или пометить для повторной загрузки
    
    monitor = DownloadMonitor()
    monitor.add_callback(on_download_complete)
```

## 📈 Статистика и аналитика

### Сводный отчет
```python
def generate_integrity_report(results):
    """Генерация сводного отчета"""
    
    total_files = len(results)
    status_counts = {}
    
    for result in results:
        status = result['status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    report = {
        'summary': {
            'total_files': total_files,
            'complete': status_counts.get('COMPLETE', 0),
            'incomplete': status_counts.get('INCOMPLETE', 0),
            'corrupted': status_counts.get('CORRUPTED', 0),
            'unreadable': status_counts.get('UNREADABLE', 0)
        },
        'integrity_rate': status_counts.get('COMPLETE', 0) / total_files * 100,
        'problematic_files': [
            r for r in results 
            if r['status'] != 'COMPLETE'
        ]
    }
    
    return report
```

## 🚨 Устранение неполадок

### Частые проблемы

#### FFmpeg не найден
```bash
# Проверка установки FFmpeg
ffmpeg -version
ffprobe -version

# Windows (через Chocolatey)
choco install ffmpeg

# Linux
sudo apt install ffmpeg

# Проверка в Python
python -c "import subprocess; subprocess.run(['ffprobe', '-version'])"
```

#### Таймауты при проверке больших файлов
```python
# Увеличение таймаута
checker = VideoIntegrityChecker(timeout=300)  # 5 минут

# Или через параметры командной строки
python video_integrity_test.py --timeout 300
```

#### Ложные срабатывания на поврежденность
```python
# Настройка порога читаемости
checker = VideoIntegrityChecker(readability_threshold=0.95)  # 95% вместо 98%

# Отключение строгих проверок
checker.set_strict_mode(False)
```

### Отладка
```bash
# Максимальная детализация
python video_integrity_test.py --verbose --debug

# Тест конкретного файла с логированием
python video_integrity_test.py --file "problem_file.mkv" --log-level DEBUG

# Сохранение FFmpeg команд для анализа
python video_integrity_test.py --save-commands --output-dir "/temp/debug"
```

## 🔄 Автоматизация и интеграция

### Cron задача для регулярной проверки
```bash
# Добавить в crontab
0 2 * * * cd /path/to/PlexAudioConverter && python Tools/video_integrity_test.py --directory "/media/downloads" --json > /var/log/integrity_check.json
```

### Интеграция с системой уведомлений
```python
def setup_integrity_notifications():
    """Настройка уведомлений о проблемах"""
    
    def check_and_notify(directory):
        results = batch_integrity_test(directory)
        problematic = [r for r in results if r['status'] != 'COMPLETE']
        
        if problematic:
            message = f"🚨 Найдено {len(problematic)} проблемных файлов:\n"
            for file_info in problematic[:5]:  # Первые 5
                message += f"• {Path(file_info['file']).name}: {file_info['status']}\n"
            
            # Отправка в Telegram
            send_telegram_message(message)
    
    return check_and_notify
```

### GitHub Actions для автоматического тестирования
```yaml
name: Video Integrity Tests
on:
  schedule:
    - cron: '0 2 * * *'  # Каждый день в 2:00
  workflow_dispatch:

jobs:
  integrity-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install FFmpeg
        run: sudo apt-get install ffmpeg
      - name: Run integrity tests
        run: |
          python Tools/video_integrity_test.py --directory ./test_videos --json > integrity_results.json
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: integrity-test-results
          path: integrity_results.json
```

---

*Этот инструмент обеспечивает высокую точность детекции проблемных видеофайлов и помогает поддерживать качество медиатеки.*
