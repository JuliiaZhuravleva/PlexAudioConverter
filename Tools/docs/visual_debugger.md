# 🎨 Visual Debugger

Инструмент для отладки генерации HTML→PNG карточек уведомлений. Позволяет тестировать рендеринг, обрезку и качество визуальных элементов системы уведомлений.

## 🎯 Назначение

- **Отладка** процесса рендеринга HTML в PNG
- **Тестирование** алгоритмов обрезки белых полей
- **Проверка** качества генерируемых карточек
- **Сравнение** различных настроек рендеринга

## 🔧 Функциональность

### Типы карточек
- **Summary Card** - сводная статистика конвертации
- **File Info Card** - информация о файле
- **Conversion Card** - процесс конвертации
- **Custom Card** - пользовательские шаблоны

### Возможности отладки
- Рендеринг с различными viewport размерами
- Сравнение до/после обрезки
- Анализ альфа-канала для точной обрезки
- Генерация отчетов о качестве
- Тестирование fallback режимов

## 🚀 Использование

### Базовые команды
```bash
# Простая отладка всех карточек
python visual_debugger.py --outdir /temp/debug

# Отладка конкретного типа карточки
python visual_debugger.py --case summary --outdir /temp/debug

# Без обрезки (для сравнения)
python visual_debugger.py --no-trim --outdir /temp/debug

# Кастомный viewport
python visual_debugger.py --viewport 1920x1080 --outdir /temp/debug
```

### Параметры командной строки
- `--outdir DIR` - директория для результатов отладки
- `--case TYPE` - тип карточки (summary|file|conversion|all)
- `--no-trim` - отключить обрезку белых полей
- `--viewport WIDTHxHEIGHT` - размер viewport для рендеринга
- `--verbose` - подробное логирование
- `--compare` - сравнение с эталонными изображениями

## 📋 Процесс отладки

### Этап 1: Подготовка данных
```
🔧 Генерация тестовых данных
├─ Создание mock объектов для карточек
├─ Подготовка различных сценариев
├─ Загрузка HTML/CSS шаблонов
└─ Проверка доступности html2image и PIL
```

### Этап 2: Рендеринг
```
🎨 Процесс рендеринга
├─ Генерация HTML из шаблонов
├─ Рендеринг в PNG через html2image
├─ Сохранение исходных изображений
└─ Логирование параметров рендеринга
```

### Этап 3: Обрезка и анализ
```
✂️ Обработка изображений
├─ Анализ альфа-канала для границ
├─ Обрезка белых полей
├─ Сравнение размеров до/после
└─ Генерация отчета качества
```

## 🔍 Детали реализации

### Основной класс отладчика
```python
class VisualDebugger:
    def __init__(self, output_dir="/temp/viz_debug"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Проверка зависимостей
        self.html2image_available = HTML2IMAGE_AVAILABLE
        self.pil_available = PIL_AVAILABLE
        
    def debug_card_generation(self, card_type="all"):
        """Основная функция отладки"""
        
        if card_type == "all":
            self._debug_all_cards()
        else:
            self._debug_specific_card(card_type)
```

### Генерация тестовых данных
```python
def create_test_data(self):
    """Создание тестовых данных для карточек"""
    
    return {
        'summary': {
            'total_files': 15,
            'converted': 12,
            'failed': 2,
            'skipped': 1,
            'total_size': '4.2 GB',
            'processing_time': '1h 23m'
        },
        'file_info': {
            'filename': 'Movie.2024.1080p.BluRay.x264-GROUP.mkv',
            'size': '8.5 GB',
            'duration': '2h 15m',
            'video_codec': 'H.264',
            'audio_codec': 'DTS-HD MA 5.1'
        },
        'conversion': {
            'filename': 'Series.S01E01.1080p.WEB-DL.mkv',
            'progress': 75,
            'current_step': 'Audio conversion',
            'estimated_time': '5m 32s'
        }
    }
```

## 📊 Результаты отладки

### Структура выходной директории
```
/temp/viz_debug/
├── summary_card/
│   ├── raw_render.png          # Исходный рендер
│   ├── trimmed_result.png      # После обрезки
│   ├── alpha_analysis.png      # Анализ альфа-канала
│   └── debug_info.json        # Метаданные
├── file_info_card/
│   ├── raw_render.png
│   ├── trimmed_result.png
│   └── debug_info.json
├── conversion_card/
│   ├── raw_render.png
│   ├── trimmed_result.png
│   └── debug_info.json
└── debug_report.html          # Сводный отчет
```

### Отчет отладки
```json
{
  "debug_session": {
    "timestamp": "2024-01-15T10:30:00",
    "viewport": "1365x768",
    "trim_enabled": true,
    "html2image_version": "1.1.0"
  },
  "cards": {
    "summary_card": {
      "render_success": true,
      "render_time": 2.3,
      "original_size": [1365, 400],
      "trimmed_size": [320, 180],
      "compression_ratio": 0.86,
      "alpha_channel": true,
      "quality_score": 9.2
    },
    "file_info_card": {
      "render_success": true,
      "render_time": 1.8,
      "original_size": [1365, 350],
      "trimmed_size": [380, 160],
      "compression_ratio": 0.82,
      "alpha_channel": true,
      "quality_score": 9.5
    }
  }
}
```

### HTML отчет
Генерируется интерактивный HTML отчет с:
- Превью всех карточек
- Сравнение до/после обрезки
- Метрики качества
- Рекомендации по улучшению

## 🛠️ Расширенные возможности

### A/B тестирование шаблонов
```python
def ab_test_templates(self):
    """Сравнение различных версий шаблонов"""
    
    template_variants = [
        'templates/card_styles.css',
        'templates/card_styles_v2.css',
        'templates/card_styles_dark.css'
    ]
    
    for variant in template_variants:
        self._render_with_template(variant)
        
    self._compare_variants()
```

### Тест производительности
```python
def performance_test(self, iterations=100):
    """Тест производительности рендеринга"""
    
    times = []
    for i in range(iterations):
        start_time = time.time()
        self._render_summary_card()
        end_time = time.time()
        times.append(end_time - start_time)
    
    return {
        'average_time': sum(times) / len(times),
        'min_time': min(times),
        'max_time': max(times),
        'total_time': sum(times)
    }
```

### Интеграция с основным генератором
```python
def test_integration_with_main_generator(self):
    """Тест интеграции с HtmlVisualGenerator"""
    
    if not GEN_AVAILABLE:
        print("⚠️ HtmlVisualGenerator недоступен")
        return
    
    generator = HtmlVisualGenerator()
    
    # Тест генерации через основной класс
    test_data = self.create_test_data()
    
    for card_type, data in test_data.items():
        try:
            result = generator.generate_card(card_type, data)
            self._validate_generated_card(result)
        except Exception as e:
            print(f"❌ Ошибка в {card_type}: {e}")
```

## 🎨 Кастомизация и настройка

### Настройка CSS стилей
```python
def test_css_variations(self):
    """Тестирование различных CSS стилей"""
    
    css_variants = {
        'default': self._load_default_css(),
        'dark_theme': self._load_dark_theme_css(),
        'compact': self._load_compact_css(),
        'minimal': self._load_minimal_css()
    }
    
    for theme_name, css_content in css_variants.items():
        self._render_with_custom_css(theme_name, css_content)
```

### Тест различных размеров viewport
```python
def test_viewport_sizes(self):
    """Тестирование различных размеров viewport"""
    
    viewports = [
        (1920, 1080),  # Full HD
        (1366, 768),   # Стандартный ноутбук
        (800, 600),    # Компактный
        (1200, 800)    # Широкий
    ]
    
    for width, height in viewports:
        self._render_with_viewport(width, height)
```

## 🚨 Устранение неполадок

### Частые проблемы

#### html2image не установлена
```bash
# Установка html2image
pip install html2image

# Проверка установки
python -c "from html2image import Html2Image; print('OK')"
```

#### Проблемы с Chrome/Chromium
```bash
# Linux - установка Chromium
sudo apt install chromium-browser

# Windows - html2image автоматически найдет Chrome
# Или указать путь явно:
export CHROME_PATH="/path/to/chrome"
```

#### PIL/Pillow недоступна
```bash
# Установка Pillow
pip install Pillow

# Проверка
python -c "from PIL import Image; print('OK')"
```

#### Некорректная обрезка
```python
# Настройка параметров обрезки
debugger = VisualDebugger()
debugger.set_trim_threshold(10)  # Порог для обрезки
debugger.set_alpha_threshold(128)  # Порог альфа-канала
```

### Отладка проблем
```bash
# Максимальная детализация
python visual_debugger.py --verbose --debug --outdir /temp/debug

# Отключение обрезки для диагностики
python visual_debugger.py --no-trim --outdir /temp/debug

# Тест конкретной карточки
python visual_debugger.py --case summary --verbose --outdir /temp/debug

# Сохранение промежуточных файлов
python visual_debugger.py --keep-temp --outdir /temp/debug
```

## 🔄 Автоматизация и CI/CD

### Автоматические тесты визуального качества
```python
def automated_visual_tests():
    """Автоматические тесты для CI/CD"""
    
    debugger = VisualDebugger("/temp/ci_visual_tests")
    
    # Тест базовой функциональности
    results = debugger.run_basic_tests()
    
    # Проверка качества
    for card_type, result in results.items():
        assert result['render_success'], f"Рендеринг {card_type} неуспешен"
        assert result['quality_score'] > 8.0, f"Низкое качество {card_type}"
        
    return results
```

### GitHub Actions
```yaml
name: Visual Debugger Tests
on: [push, pull_request]

jobs:
  visual-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install html2image pillow
          sudo apt-get install chromium-browser
      - name: Run visual debugger
        run: |
          python Tools/visual_debugger.py --outdir ./visual_test_results --case all
      - name: Upload visual results
        uses: actions/upload-artifact@v3
        with:
          name: visual-test-results
          path: ./visual_test_results/
```

### Регрессионное тестирование
```python
def regression_test(baseline_dir, current_dir):
    """Сравнение с эталонными изображениями"""
    
    from PIL import Image, ImageChops
    
    baseline_images = Path(baseline_dir).glob('*.png')
    
    for baseline_path in baseline_images:
        current_path = Path(current_dir) / baseline_path.name
        
        if not current_path.exists():
            print(f"❌ Отсутствует: {baseline_path.name}")
            continue
            
        # Сравнение изображений
        baseline_img = Image.open(baseline_path)
        current_img = Image.open(current_path)
        
        diff = ImageChops.difference(baseline_img, current_img)
        
        if diff.getbbox():
            print(f"⚠️ Различия в: {baseline_path.name}")
        else:
            print(f"✅ Идентично: {baseline_path.name}")
```

---

*Этот инструмент обеспечивает высокое качество визуальных уведомлений и помогает выявить проблемы рендеринга на раннем этапе.*
