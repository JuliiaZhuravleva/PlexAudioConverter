"""
Чистый генератор визуальных карточек на базе HTML-шаблонов и CSS.
- Без дублирования
- Без встроенного HTML мусора
- Поддержка безопасной обрезки (trim) белых полей при помощи PIL
- Использует шаблоны из каталога `templates`

Ожидаемые шаблоны:
  templates/
    ├─ file_info_template.html
    ├─ conversion_template.html
    ├─ summary_template.html
    └─ card_styles.css               # опционально; если нет — применится минимальный CSS-оверрайд
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

try:
    from html2image import Html2Image
    HTML2IMAGE_AVAILABLE = True
except Exception:  # ImportError и пр.
    Html2Image = None  # type: ignore
    HTML2IMAGE_AVAILABLE = False

try:
    from PIL import Image, ImageChops, ImageStat
    PIL_AVAILABLE = True
except Exception:
    Image = ImageChops = None  # type: ignore
    PIL_AVAILABLE = False

# Локальный логгер проекта
from .logger import logger


# Минимальный CSS-оверрайд на случай отсутствия файла стилей.
# Задача: прозрачный фон и «tight» размер по содержимому, без флекс-центрирования на <body>.
_FALLBACK_MIN_CSS = (
    "html,body{background:transparent!important;margin:0!important;padding:0!important;"
    "display:block!important;width:max-content!important;height:max-content!important;}"
)


class HtmlVisualGenerator:
    """Генератор карточек через HTML/CSS и html2image.

    Публичные методы:
      - generate_file_info_card(file_info)
      - generate_conversion_card(conversion_info)
      - generate_summary_card(summary_info)
      - cleanup_temp_files(max_age_hours=24)

    Примечание: html2image рендерит *весь вьюпорт*, поэтому включена
    безопасная пост-обработка (обрезка) для tight-изображений.
    """

    def __init__(self, temp_dir: str = "temp", templates_dir: str = "templates", do_trim: bool = True):
        project_root = Path(__file__).parent.parent
        self.temp_dir = (project_root / temp_dir).resolve()
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.templates_dir = (project_root / templates_dir).resolve()
        if not self.templates_dir.exists():
            logger.warning("Каталог шаблонов не найден: %s", self.templates_dir)

        self.do_trim = do_trim

        if HTML2IMAGE_AVAILABLE:
            self.hti = Html2Image(output_path=str(self.temp_dir))
        else:
            self.hti = None
            logger.warning("html2image недоступна — генерация карточек отключена")

        if not PIL_AVAILABLE and self.do_trim:
            logger.warning("PIL недоступна — обрезка белых полей будет пропущена")

    # --------------------------- Публичный API --------------------------- #

    def generate_file_info_card(self, file_info: Dict) -> Optional[Path]:
        html = self._create_file_info_html(file_info)
        return self._render_card(html, filename_prefix="file_info")

    def generate_conversion_card(self, conversion_info: Dict) -> Optional[Path]:
        html = self._create_conversion_html(conversion_info)
        return self._render_card(html, filename_prefix="conversion")

    def generate_summary_card(self, summary_info: Dict) -> Optional[Path]:
        html = self._create_summary_html(summary_info)
        return self._render_card(html, filename_prefix="summary")

    def cleanup_temp_files(self, max_age_hours: int = 24) -> None:
        """Удаляет старые PNG из временной папки."""
        try:
            now = datetime.now().timestamp()
            threshold = max_age_hours * 3600
            for p in self.temp_dir.glob("*.png"):
                age = now - p.stat().st_mtime
                if age > threshold:
                    p.unlink(missing_ok=True)
                    logger.debug("Удален временный файл: %s", p)
        except Exception as e:
            logger.error("Ошибка очистки временных файлов: %s", e)

    # -------------------------- Рендер-ядро ----------------------------- #

    def _render_card(self, html_content: str, filename_prefix: str) -> Optional[Path]:
        if not (HTML2IMAGE_AVAILABLE and self.hti):
            return None

        css_str = self._load_css()
        filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        try:
            # Рендерим вьюпорт по умолчанию; затем (опционально) подрезаем до контента.
            self.hti.screenshot(html_str=html_content, css_str=css_str, save_as=filename)
        except Exception as e:
            logger.error("Ошибка рендера html2image: %s", e)
            return None

        path = self.temp_dir / filename
        if not path.exists():
            return None

        if self.do_trim and PIL_AVAILABLE:
            return self._trim_whitespace(path)
        return path

    # ------------------------- HTML-шаблоны ----------------------------- #

    def _create_file_info_html(self, file_info: Dict) -> str:
        title: str = file_info.get("title", "📁 Информация о файле")
        filename: str = file_info.get("name", "Неизвестно")
        size_str: str = self._format_file_size(file_info.get("size", 0))
        resolution: str = file_info.get("resolution", "Неизвестно")
        audio_tracks = file_info.get("audio_tracks", []) or []

        # Сокращаем длинное имя для аккуратной верстки
        if len(filename) > 45:
            filename = filename[:42] + "..."

        tracks_html = []
        for track in audio_tracks[:4]:
            ch = track.get("channels", 0)
            lang = (track.get("language", "unknown") or "").upper()
            codec = (track.get("codec", "unknown") or "").upper()
            tclass = "stereo" if ch == 2 else ("surround" if ch >= 6 else "other")
            tracks_html.append(
                f'<div class="audio-track {tclass}"><span class="channels">{ch}ch</span>'
                f"<span class=\"language\">{lang}</span><span class=\"codec\">{codec}</span></div>"
            )
        if len(audio_tracks) > 4:
            tracks_html.append(f"<div class=\"more-tracks\">... и еще {len(audio_tracks) - 4} дорожек</div>")

        template = self._load_template("file_info_template.html")
        return template.format(
            title=title,
            filename=filename,
            size=size_str,
            resolution=resolution,
            tracks_html="\n".join(tracks_html),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    def _create_conversion_html(self, conversion_info: Dict) -> str:
        status = conversion_info.get("status", "unknown")
        filename = conversion_info.get("filename", "Неизвестно")
        if len(filename) > 40:
            filename = filename[:37] + "..."

        src = conversion_info.get("source_track", {}) or {}
        tgt = conversion_info.get("target_track", {}) or {}

        if status == "success":
            status_icon, status_text, status_class = "✅", "Конвертация завершена", "success"
        elif status == "error":
            status_icon, status_text, status_class = "❌", "Ошибка конвертации", "error"
        else:
            status_icon, status_text, status_class = "🔄", "Конвертация в процессе", "processing"

        template = self._load_template("conversion_template.html")
        return template.format(
            status_class=status_class,
            status_icon=status_icon,
            status_text=status_text,
            filename=filename,
            src_channels=src.get("channels", 6),
            src_codec=(src.get("codec", "unknown") or "").upper(),
            tgt_channels=tgt.get("channels", 2),
            tgt_codec=(tgt.get("codec", "AAC") or "AAC").upper(),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    def _create_summary_html(self, summary_info: Dict) -> str:
        stats = summary_info.get("stats", {}) or {}
        recent = summary_info.get("recent_files", []) or []
        is_startup: bool = bool(summary_info.get("startup", False))

        title = "🚀 Мониторинг запущен" if is_startup else "📊 Сводка по директории"
        total = stats.get("total_files", 0)
        processed = stats.get("processed_files", 0)
        pending = stats.get("pending_files", 0)
        errors = stats.get("error_files", 0)

        startup_info = ""
        if is_startup:
            directory = summary_info.get("directory", "") or ""
            interval = summary_info.get("interval", 0)
            if len(directory) > 50:
                directory = "..." + directory[-47:]
            startup_info = (
                f'<div class="startup-info"><div class="detail">📁 {directory}</div>'
                f"<div class=\"detail\">⏱ Интервал: {interval}с</div></div>"
            )

        files_title = "📁 Файлы в директории:" if is_startup else "📁 Последние файлы:"
        display_count = 6 if is_startup else 5

        file_items = []
        for info in recent[:display_count]:
            name = info.get("name", "Неизвестно")
            if len(name) > 40:
                name = name[:37] + "..."
            st = info.get("status", "unknown")
            emoji = {"processed": "✅", "pending": "⏳", "error": "❌"}.get(st, "❓")
            file_items.append(
                f'<div class="file-item {st}"><span class="status-icon">{emoji}</span>'
                f"<span class=\"filename\">{name}</span></div>"
            )
        if len(recent) > display_count:
            file_items.append(f"<div class=\"more-files\">... и еще {len(recent) - display_count} файлов</div>")

        template = self._load_template("summary_template.html")
        return template.format(
            title=title,
            startup_info=startup_info,
            total_files=total,
            processed_files=processed,
            pending_files=pending,
            error_files=errors,
            files_title=files_title,
            files_html="\n".join(file_items),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    # ----------------------------- Утилиты ------------------------------ #

    def _load_template(self, name: str) -> str:
        path = self.templates_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Не найден шаблон: {path}")
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            raise RuntimeError(f"Ошибка чтения шаблона {path}: {e}")

    def _load_css(self) -> str:
        css_path = self.templates_dir / "card_styles.css"
        if css_path.exists():
            try:
                return css_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Не удалось загрузить CSS (%s), применяю минимальный fallback", e)
        return _FALLBACK_MIN_CSS

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        if not isinstance(size_bytes, (int, float)) or size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(units) - 1:
            size /= 1024.0
            i += 1
        return f"{size:.1f} {units[i]}"

    def _trim_whitespace(self, image_path: Path) -> Path:
        """Robust trim that prefers the alpha channel (if present).
        - If RGBA: build a mask from alpha > THRESH and crop by mask bbox.
        - Else: fallback to difference-from-background (corner color) with tolerance.
        Returns path to final PNG. If trimming fails → returns original path.
        """
        if not (PIL_AVAILABLE and image_path.exists()):
            return image_path

        THRESH = 2  # consider alpha <= 2 as transparent
        try:
            with Image.open(image_path) as img:
                mode = img.mode
                # 1) Alpha-first path
                if mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info):
                    rgba = img.convert("RGBA")
                    r, g, b, a = rgba.split()
                    # Build binary mask: 255 where alpha > THRESH
                    mask = a.point(lambda v: 255 if v > THRESH else 0, mode='1')
                    bbox = mask.getbbox()
                    if bbox:
                        # Pad bbox by 1px to keep soft shadows intact
                        x1, y1, x2, y2 = bbox
                        x1 = max(0, x1 - 1); y1 = max(0, y1 - 1)
                        x2 = min(rgba.width, x2 + 1); y2 = min(rgba.height, y2 + 1)
                        cropped = rgba.crop((x1, y1, x2, y2))
                        out = image_path.with_name(f"cropped_{image_path.name}")
                        cropped.save(out, 'PNG', optimize=True)
                        image_path.unlink(missing_ok=True)
                        return out
                    return image_path

                # 2) Fallback: difference vs. corner background (RGB images)
                bg_color = img.getpixel((0, 0))
                bg = Image.new(img.mode, img.size, bg_color)
                diff = ImageChops.difference(img, bg)
                # small tolerance for JPEG-like noise
                diff = ImageChops.add(diff, diff, 2.0, -10)
                bbox = diff.getbbox()
                if bbox:
                    cropped = img.crop(bbox)
                    out = image_path.with_name(f"cropped_{image_path.name}")
                    cropped.save(out, 'PNG', optimize=True)
                    image_path.unlink(missing_ok=True)
                    return out
                return image_path
        except Exception:
            return image_path
