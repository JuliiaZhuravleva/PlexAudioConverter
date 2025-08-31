# 🎧 Руководство по объективной проверке качества звука

## Что измеряет анализатор

### 1. **LUFS (Loudness Units relative to Full Scale)**
Стандарт измерения громкости EBU R128, используемый в вещании и стриминге.

**Целевые значения для ТВ/Plex:**
- **Integrated LUFS**: -23 LUFS (±7)
  - ✅ Хорошо: -24 до -16 LUFS
  - ⚠️ Тихо: меньше -24 LUFS
  - ⚠️ Громко: больше -16 LUFS

- **Loudness Range (LRA)**: 7 LU (±3)
  - ✅ Хорошо: 4-15 LU
  - ❌ Сжато: меньше 4 LU (потеря динамики)
  - ❌ Слишком динамично: больше 15 LU (придется регулировать громкость)

- **True Peak**: не выше -1 dBTP
  - ✅ Хорошо: меньше -1 dBTP
  - ❌ Клиппинг: больше -1 dBTP

### 2. **Частотный баланс**
Распределение энергии по частотному спектру.

**Оптимальное распределение:**
- 🔵 **Низкие частоты** (<250 Hz): 15-30%
  - Басы, взрывы, низкий мужской голос
- 🟢 **Средние частоты** (250-4000 Hz): 40-60%
  - ДИАЛОГИ, основная часть голоса
- 🔴 **Высокие частоты** (>4000 Hz): 15-30%
  - Детали, шипящие, тарелки

### 3. **Присутствие диалогов**
Анализ частот человеческого голоса (85-3000 Hz).

**Целевые значения:**
- ✅ Хорошо: >35% энергии в диапазоне голоса
- ⚠️ Слабо: 20-35%
- ❌ Плохо: <20% (диалоги потеряны)

### 4. **Стерео баланс**
Соотношение левого и правого каналов.

**Нормальный баланс:**
- ✅ 45-55% на каждый канал
- ⚠️ Дисбаланс: отклонение >10%

## 🚀 Использование анализатора

### Установка дополнительных библиотек

```bash
# Для полного функционала анализатора
pip install librosa soundfile matplotlib numpy

# Минимальный набор (только LUFS анализ)
pip install numpy
```

### Быстрая проверка одного файла

```bash
# Простой анализ
python Tools/audio_quality_analyzer.py "video.mp4"

# Сравнение с оригиналом
python Tools/audio_quality_analyzer.py "converted.mp4" --compare "original.mp4"

# Без графиков (быстрее)
python Tools/audio_quality_analyzer.py "video.mp4" --no-plots

# Вывод в JSON для автоматизации
python Tools/audio_quality_analyzer.py "video.mp4" --json
```

### Пакетная проверка

```bash
# Анализ всех файлов в папке
python Tools/audio_quality_analyzer.py "E:\Download\Movie" --batch
```

## 📊 Интерпретация результатов

### Оценка качества (Overall Score)

**80-100% - ОТЛИЧНО** 🎉
- Звук полностью готов к просмотру
- Диалоги четкие, громкость оптимальная
- Никаких действий не требуется

**60-79% - ХОРОШО** 👍
- Звук приемлемый
- Могут быть небольшие недостатки
- Рекомендуется проверить на реальном устройстве

**40-59% - УДОВЛЕТВОРИТЕЛЬНО** ⚠️
- Есть заметные проблемы
- Требуется доработка параметров
- Проверьте рекомендации

**0-39% - ПЛОХО** ❌
- Серьезные проблемы с качеством
- Нужно пересмотреть параметры конвертации
- Возможно, исходный файл проблемный

### Типичные проблемы и решения

#### Проблема: "Слишком тихий звук"
```
❌ Громкость вне диапазона: -28.5 LUFS
```
**Решение:** Увеличьте громкость в конфигурации:
```python
'loudnorm_params': 'loudnorm=I=-20:TP=-1:LRA=7'  # Увеличили до -20
```

#### Проблема: "Диалоги не слышны"
```
❌ Слабое присутствие диалогов: 18.3%
```
**Решение:** Усильте центральный канал:
```python
# Увеличьте коэффициент FC с 1.414 до 2.0
'downmix_formula': 'pan=stereo|FL=2.0*FC+0.707*FL+...'
```

#### Проблема: "Звук слишком сжатый"
```
❌ Динамический диапазон: 2.5 LU
```
**Решение:** Уменьшите компрессию:
```python
'use_loudnorm': False  # Отключите нормализацию
# или измените параметры
'loudnorm_params': 'loudnorm=I=-23:TP=-2:LRA=11'  # Увеличили LRA
```

## 📈 Автоматизация проверки

### Интеграция в основной скрипт

Добавьте в `audio_converter.py` после конвертации:

```python
# После успешной конвертации
if self.convert_audio(input_file, output_file, ...):
    # Автоматическая проверка качества
    analyzer = AudioQualityAnalyzer()
    report = analyzer.generate_report(output_file)
    
    # Проверяем оценку
    score = report['evaluation']['overall_score']
    if score < 60:
        logger.warning(f"⚠️ Низкое качество: {score}%. Требуется проверка!")
        # Можно отправить уведомление в Telegram
```

### Создание автоматического pipeline

```python
#!/usr/bin/env python3
"""
Полный pipeline: конвертация + проверка качества
"""

import subprocess
from pathlib import Path

def process_with_quality_check(video_file: Path):
    """Конвертация с автоматической проверкой"""
    
    # 1. Конвертируем
    converted_file = video_file.with_suffix('.stereo.mp4')
    subprocess.run([
        'python', 'audio_converter.py',
        str(video_file.parent),
        '--file', str(video_file)
    ])
    
    # 2. Проверяем качество
    result = subprocess.run([
        'python', 'audio_quality_analyzer.py',
        str(converted_file),
        '--json'
    ], capture_output=True, text=True)
    
    import json
    report = json.loads(result.stdout)
    score = report['evaluation']['overall_score']
    
    # 3. Принимаем решение
    if score >= 60:
        print(f"✅ Файл прошел проверку: {score}%")
        # Заменяем оригинал
        video_file.unlink()
        converted_file.rename(video_file)
    else:
        print(f"❌ Низкое качество: {score}%")
        # Оставляем оригинал, удаляем плохую конвертацию
        converted_file.unlink()
        
        # Пробуем другие параметры
        retry_with_different_params(video_file)

def retry_with_different_params(video_file: Path):
    """Повторная конвертация с другими параметрами"""
    # Логика для подбора параметров
    pass
```

## 🎯 Целевые метрики для разных сценариев

### Для ночного просмотра
```json
{
  "lufs_integrated": -20,  // Громче стандарта
  "lufs_range": 5,         // Меньше динамики
  "dialog_boost": 2.0      // Усиленные диалоги
}
```

### Для дневного просмотра
```json
{
  "lufs_integrated": -23,  // Стандарт
  "lufs_range": 10,        // Больше динамики
  "dialog_boost": 1.414    // Стандартные диалоги
}
```

### Для наушников
```json
{
  "lufs_integrated": -16,  // Можно тише
  "lufs_range": 12,        // Максимум динамики
  "dialog_boost": 1.0      // Минимальное усиление
}
```

## 📝 Экспорт результатов

### HTML отчет
Анализатор автоматически создает:
- `video.quality_report.json` - детальный отчет
- `video.quality_analysis.png` - визуализация

### Сводная таблица для Excel

```python
import pandas as pd
import json

def create_excel_report(json_files: List[Path]):
    """Создание Excel отчета из JSON файлов"""
    
    data = []
    for json_file in json_files:
        with open(json_file) as f:
            report = json.load(f)
            
        row = {
            'Файл': report['file'],
            'Оценка': report['evaluation']['overall_score'],
            'LUFS': report['analysis']['lufs']['integrated'],
            'Диапазон': report['analysis']['lufs']['range'],
            'Диалоги %': report['analysis']['dialog']['dialog_ratio'] * 100,
            'Вердикт': report['evaluation']['verdict']
        }
        data.append(row)
    
    df = pd.DataFrame(data)
    df.to_excel('quality_report.xlsx', index=False)
    print("Отчет сохранен: quality_report.xlsx")
```

## ⚡ Быстрые команды

### Проверка всей библиотеки
```bash
# Windows PowerShell
Get-ChildItem -Path "E:\Download\Movie" -Filter "*.mp4" -Recurse | 
ForEach-Object { 
    python audio_quality_analyzer.py $_.FullName --no-plots
}

# Linux/Mac bash
find /path/to/movies -name "*.mp4" -exec python audio_quality_analyzer.py {} \;
```

### Поиск проблемных файлов
```bash
# Найти файлы с оценкой ниже 60%
python -c "
import json
from pathlib import Path

for report_file in Path('.').glob('**/*.quality_report.json'):
    with open(report_file) as f:
        report = json.load(f)
    score = report['evaluation']['overall_score']
    if score < 60:
        print(f'{score:.0f}% - {report_file.stem}')
"
```

## 🔬 Дополнительные метрики (для продвинутых)

### Spectral Centroid
Показывает "яркость" звука. Для диалогов должен быть в районе 1500-3000 Hz.

### Spectral Rolloff
Частота, ниже которой содержится 85% энергии. Для сбалансированного звука: 4000-8000 Hz.

### Zero Crossing Rate
Показатель "шумности". Высокие значения могут указывать на искажения.

## 📚 Полезные ссылки

- [EBU R128 стандарт](https://tech.ebu.ch/docs/r/r128.pdf)
- [LUFS объяснение](https://www.masteringthemix.com/blogs/learn/76296773-mastering-audio-for-soundcloud-itunes-spotify-and-youtube)
- [Частоты человеческого голоса](https://www.dpamicrophones.com/mic-university/facts-about-speech-intelligibility)

---

*Этот анализатор поможет объективно оценить качество конвертированного звука и найти оптимальные параметры для вашей системы.*