# 🎧 Audio Quality Analyzer

Комплексный инструмент для объективного анализа качества аудио после конвертации. Измеряет LUFS, частотный баланс, присутствие диалогов, стерео-баланс и другие критически важные параметры. Предназначен для единых правил контроля качества в медиатеке и автоматизации пайплайнов.

## 🎯 Назначение

- **Объективная оценка** качества конвертированного аудио
- **Сравнение** с оригинальными файлами
- **Автоматизация** проверки качества в pipeline
- **Подбор оптимальных** параметров конвертации

## 📊 Анализируемые метрики

### LUFS (Loudness Units relative to Full Scale)

Стандарт измерения громкости **EBU R128**:

- **Integrated LUFS** (общая громкость): целевой −23 LUFS (±7)
    - ✅ Хорошо: −24…−16 LUFS
    - ⚠️ Тихо: < −24 LUFS
    - ⚠️ Громко: > −16 LUFS
- **Loudness Range, LRA** (динамический диапазон): целевой 7 LU (±3)
    - ✅ Хорошо: 4–15 LU
    - ❌ Сжато: < 4 LU (потеря динамики)
    - ❌ Слишком динамично: > 15 LU (потребуется частая регулировка громкости)
- **True Peak** (дБ от полной шкалы, dBTP):
    - ✅ Хорошо: < −1 dBTP
    - ❌ Клиппинг: ≥ −1 dBTP

### Частотный баланс

Распределение энергии по спектру:

- 🔵 **Низкие** (< 250 Hz): 15–30% — басы, взрывы, низкий мужской голос
- 🟢 **Средние** (250–4000 Hz): 40–60% — *диалоги*, основная часть голоса
- 🔴 **Высокие** (> 4000 Hz): 15–30% — детали, шипящие, тарелки

### Присутствие диалогов

Анализ частот человеческого голоса (≈ 85–3000 Hz):

- ✅ Хорошо: > 35% энергии в диапазоне голоса
- ⚠️ Слабо: 20–35%
- ❌ Плохо: < 20% (диалоги потеряны)

### Стерео-баланс

Соотношение энергии левого/правого каналов:

- ✅ Норма: 45–55% на каждый канал
- ⚠️ Дисбаланс: отклонение > 10%

## 🚀 Использование

### Базовые команды
```bash
# Простой анализ файла
python audio_quality_analyzer.py "video.mp4"

# Сравнение с оригиналом
python audio_quality_analyzer.py "converted.mp4" --compare "original.mp4"

# Быстрый анализ без графиков
python audio_quality_analyzer.py "video.mp4" --no-plots

# JSON вывод для автоматизации
python audio_quality_analyzer.py "video.mp4" --json
```

### Пакетная обработка
```bash
# Анализ всех файлов в папке
python audio_quality_analyzer.py "E:\Download\Movie" --batch

# Только определенные форматы
python audio_quality_analyzer.py "E:\Download\Movie" --batch --formats mp4,mkv
```

### Параметры командной строки
- `--compare FILE` - сравнить с оригинальным файлом
- `--no-plots` - отключить генерацию графиков
- `--json` - вывод в JSON формате
- `--batch` - пакетная обработка директории
- `--formats EXT1,EXT2` - фильтр по расширениям
- `--output-dir DIR` - директория для отчетов
- `--verbose` - подробный вывод

## 📈 Интерпретация результатов

### Общая оценка качества
```
80-100% - ОТЛИЧНО 🎉
├─ Звук готов к просмотру
├─ Диалоги четкие
└─ Громкость оптимальная

60-79% - ХОРОШО 👍
├─ Звук приемлемый
├─ Возможны небольшие недостатки
└─ Рекомендуется проверка

40-59% - УДОВЛЕТВОРИТЕЛЬНО ⚠️
├─ Заметные проблемы
├─ Требуется доработка
└─ Проверьте рекомендации

0-39% - ПЛОХО ❌
├─ Серьезные проблемы
├─ Пересмотрите параметры
└─ Возможно проблемный исходник
```

### Типичные проблемы и решения

#### Слишком тихий звук
```
❌ Громкость: -28.5 LUFS (норма: -23±7)
```
**Решение:**
```python
'loudnorm_params': 'loudnorm=I=-20:TP=-1:LRA=7'  # Увеличить до -20
```

#### Диалоги не слышны
```
❌ Присутствие диалогов: 18.3% (норма: >35%)
```
**Решение:**
```python
# Усилить центральный канал
'downmix_formula': 'pan=stereo|FL=2.0*FC+0.707*FL+0.707*BL|FR=2.0*FC+0.707*FR+0.707*BR'
```

#### Сжатый звук
```
❌ Динамический диапазон: 2.5 LU (норма: 4-15)
```
**Решение:**
```python
'use_loudnorm': False  # Отключить нормализацию
# или
'loudnorm_params': 'loudnorm=I=-23:TP=-2:LRA=11'  # Увеличить LRA
```

---

## 🧩 Сценарные профили (целевые метрики)

### Ночной просмотр

```json
{
  "lufs_integrated": -20,
  "lufs_range": 5,
  "dialog_boost": 2.0
}

```

### Дневной просмотр

```json
{
  "lufs_integrated": -23,
  "lufs_range": 10,
  "dialog_boost": 1.414
}

```

### Наушники

```json
{
  "lufs_integrated": -16,
  "lufs_range": 12,
  "dialog_boost": 1.0
}

```

---

## 🔧 Интеграция в код

### Автоматическая проверка после конвертации
```python
from Tools.audio_quality_analyzer import AudioQualityAnalyzer

def convert_with_quality_check(input_file, output_file):
    # Конвертация
    if convert_audio(input_file, output_file):
        # Проверка качества
        analyzer = AudioQualityAnalyzer()
        report = analyzer.generate_report(output_file)
        
        score = report['evaluation']['overall_score']
        if score < 60:
            logger.warning(f"⚠️ Низкое качество: {score}%")
            return False
        return True
```

### Pipeline с автоматическим подбором параметров
```python
def adaptive_conversion(video_file):
    """Конвертация с адаптивным подбором параметров"""
    
    params_variants = [
        {'loudnorm': 'I=-23:TP=-1:LRA=7'},
        {'loudnorm': 'I=-20:TP=-1:LRA=5'},  # Для ночного просмотра
        {'loudnorm': 'I=-16:TP=-1:LRA=10'}, # Для наушников
    ]
    
    for params in params_variants:
        converted_file = convert_with_params(video_file, params)
        
        analyzer = AudioQualityAnalyzer()
        report = analyzer.generate_report(converted_file)
        
        if report['evaluation']['overall_score'] >= 70:
            return converted_file  # Успех
            
        converted_file.unlink()  # Удаляем неудачную попытку
    
    return None  # Все варианты неудачны
```

## 📊 Форматы вывода

### JSON отчет
```json
{
  "file": "movie.mp4",
  "timestamp": "2024-01-15T10:30:00",
  "analysis": {
    "lufs": {
      "integrated": -23.2,
      "range": 8.5,
      "true_peak": -1.2
    },
    "frequency": {
      "low_freq_ratio": 0.25,
      "mid_freq_ratio": 0.55,
      "high_freq_ratio": 0.20
    },
    "dialog": {
      "dialog_ratio": 0.42,
      "clarity_score": 0.78
    }
  },
  "evaluation": {
    "overall_score": 85,
    "verdict": "ОТЛИЧНО",
    "recommendations": []
  }
}
```

### Визуальные отчеты
- **Спектрограмма** - частотный анализ во времени
- **Гистограмма громкости** - распределение LUFS
- **Частотный баланс** - соотношение частотных диапазонов
- **Динамический диапазон** - изменения громкости

## ⚙️ Зависимости

### Обязательные
```bash
pip install numpy matplotlib
```

### Дополнительные (для полного функционала)
```bash
pip install librosa soundfile
```

### Системные требования
- **FFmpeg/FFprobe** - для извлечения аудио
- **Python 3.8+** - основная среда выполнения
- **Свободное место** - ~100MB для временных файлов

## 🔍 Продвинутые возможности

### Кастомные метрики
```python
analyzer = AudioQualityAnalyzer()
analyzer.add_custom_metric('bass_presence', lambda audio: analyze_bass(audio))
report = analyzer.generate_report('file.mp4', include_custom=True)
```

### Профили качества
```python
# Профиль для ночного просмотра
night_profile = {
    'target_lufs': -20,
    'target_lra': 5,
    'dialog_boost': 2.0
}

analyzer.set_quality_profile(night_profile)
```

### Экспорт в Excel
```python
from pathlib import Path
import pandas as pd

def create_batch_report(directory):
    """Создание сводного Excel отчета"""
    
    reports = []
    for video_file in Path(directory).glob('*.mp4'):
        analyzer = AudioQualityAnalyzer()
        report = analyzer.generate_report(video_file)
        reports.append({
            'Файл': video_file.name,
            'Оценка': report['evaluation']['overall_score'],
            'LUFS': report['analysis']['lufs']['integrated'],
            'Диалоги %': report['analysis']['dialog']['dialog_ratio'] * 100
        })
    
    df = pd.DataFrame(reports)
    df.to_excel('quality_report.xlsx', index=False)
```

## 🚨 Устранение неполадок

### Ошибка: "FFmpeg не найден"
```bash
# Windows
choco install ffmpeg
# или скачать с https://ffmpeg.org/

# Linux
sudo apt install ffmpeg

# Проверка
ffmpeg -version
```

### Ошибка: "librosa не установлена"
```bash
pip install librosa soundfile
# Если не помогает:
conda install -c conda-forge librosa
```

### Медленная обработка
- Используйте `--no-plots` для ускорения
- Уменьшите длительность анализа в коде
- Проверьте доступное место на диске

### Неточные результаты
- Убедитесь в качестве исходного файла
- Проверьте настройки FFmpeg
- Сравните с эталонными файлами

---

## 📚 Полезные ссылки

- [EBU R128 стандарт](https://tech.ebu.ch/docs/r/r128.pdf)
- [LUFS объяснение](https://www.masteringthemix.com/blogs/learn/76296773-mastering-audio-for-soundcloud-itunes-spotify-and-youtube)
- [Частоты человеческого голоса](https://www.dpamicrophones.com/mic-university/facts-about-speech-intelligibility)

---

*Анализатор поможет объективно оценить качество и найти оптимальные параметры конвертации для вашей медиатеки.*
