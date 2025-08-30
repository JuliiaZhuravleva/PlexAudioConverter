"""
Современный генератор визуальных карточек через HTML/CSS
"""

from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
import tempfile
import os

try:
    from html2image import Html2Image
    HTML2IMAGE_AVAILABLE = True
except ImportError:
    HTML2IMAGE_AVAILABLE = False

from .logger import logger


class HtmlVisualGenerator:
    """Генератор красивых карточек через HTML/CSS"""
    
    def __init__(self, temp_dir: str = "temp"):
        # Создаем temp директорию в корне проекта
        project_root = Path(__file__).parent.parent
        self.temp_dir = project_root / temp_dir
        self.temp_dir.mkdir(exist_ok=True)
        
        # Путь к шаблонам
        self.templates_dir = project_root / "templates"
        
        if HTML2IMAGE_AVAILABLE:
            self.hti = Html2Image(output_path=str(self.temp_dir))
        else:
            self.hti = None
            logger.warning("html2image недоступна, визуальные карточки отключены")
    
    def generate_file_info_card(self, file_info: Dict) -> Optional[Path]:
        """Генерация карточки информации о файле"""
        if not HTML2IMAGE_AVAILABLE or not self.hti:
            return None
        
        try:
            html_content = self._create_file_info_html(file_info)
            css_content = self._load_css()
            
            filename = f"file_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            self.hti.screenshot(
                html_str=html_content,
                css_str=css_content,
                save_as=filename,
                size=(600, 500)
            )
            
            output_path = self.temp_dir / filename
            return output_path if output_path.exists() else None
            
        except Exception as e:
            logger.error(f"Ошибка генерации HTML карточки файла: {e}")
            return None
    
    def generate_conversion_card(self, conversion_info: Dict) -> Optional[Path]:
        """Генерация карточки конвертации"""
        if not HTML2IMAGE_AVAILABLE or not self.hti:
            return None
        
        try:
            html_content = self._create_conversion_html(conversion_info)
            css_content = self._load_css()
            
            filename = f"conversion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            self.hti.screenshot(
                html_str=html_content,
                css_str=css_content,
                save_as=filename,
                size=(600, 400)
            )
            
            output_path = self.temp_dir / filename
            return output_path if output_path.exists() else None
            
        except Exception as e:
            logger.error(f"Ошибка генерации HTML карточки конвертации: {e}")
            return None
    
    def generate_summary_card(self, summary_info: Dict) -> Optional[Path]:
        """Генерация сводной карточки"""
        if not HTML2IMAGE_AVAILABLE or not self.hti:
            return None
        
        try:
            html_content = self._create_summary_html(summary_info)
            css_content = self._load_css()
            
            filename = f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            self.hti.screenshot(
                html_str=html_content,
                css_str=css_content,
                save_as=filename,
                size=(600, 600)
            )
            
            output_path = self.temp_dir / filename
            return output_path if output_path.exists() else None
            
        except Exception as e:
            logger.error(f"Ошибка генерации HTML сводной карточки: {e}")
            return None
    
    def _create_file_info_html(self, file_info: Dict) -> str:
        """Создание HTML для карточки файла"""
        title = file_info.get('title', '📁 Информация о файле')
        filename = file_info.get('name', 'Неизвестно')
        size = self._format_file_size(file_info.get('size', 0))
        resolution = file_info.get('resolution', 'Неизвестно')
        audio_tracks = file_info.get('audio_tracks', [])
        
        # Сокращаем длинное имя файла
        if len(filename) > 45:
            filename = filename[:42] + "..."
        
        # Генерируем HTML для аудио дорожек
        tracks_html = ""
        for track in audio_tracks[:4]:  # Максимум 4 дорожки
            channels = track.get('channels', 0)
            language = track.get('language', 'unknown').upper()
            codec = track.get('codec', 'unknown').upper()
            
            track_class = 'stereo' if channels == 2 else 'surround' if channels >= 6 else 'other'
            
            tracks_html += f"""
            <div class="audio-track {track_class}">
                <span class="channels">{channels}ch</span>
                <span class="language">{language}</span>
                <span class="codec">{codec}</span>
            </div>
            """
        
        if len(audio_tracks) > 4:
            tracks_html += f'<div class="more-tracks">... и еще {len(audio_tracks) - 4} дорожек</div>'
        
        # Загружаем шаблон
        template_path = self.templates_dir / "file_info_template.html"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            return template.format(
                title=title,
                filename=filename,
                size=size,
                resolution=resolution,
                tracks_html=tracks_html,
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M')
            )
        
        # Fallback к встроенному HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body>
            <div class="card">
                <div class="header">
                    <h1 class="title">{title}</h1>
                </div>
                <div class="content">
                    <div class="file-name">{filename}</div>
                    <div class="file-details">
                        <div class="detail">
                            <span class="label">Размер:</span>
                            <span class="value">{size}</span>
                        </div>
                        <div class="detail">
                            <span class="label">Разрешение:</span>
                            <span class="value">{resolution}</span>
                        </div>
                    </div>
                    <div class="audio-section">
                        <h3>🎵 Аудио дорожки</h3>
                        <div class="audio-tracks">
                            {tracks_html}
                        </div>
                    </div>
                </div>
                <div class="footer">
                    <span class="timestamp">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _create_conversion_html(self, conversion_info: Dict) -> str:
        """Создание HTML для карточки конвертации"""
        status = conversion_info.get('status', 'unknown')
        filename = conversion_info.get('filename', 'Неизвестно')
        source_track = conversion_info.get('source_track', {})
        target_track = conversion_info.get('target_track', {})
        
        if len(filename) > 40:
            filename = filename[:37] + "..."
        
        # Определяем статус и иконку
        if status == 'success':
            status_icon = '✅'
            status_text = 'Конвертация завершена'
            status_class = 'success'
        elif status == 'error':
            status_icon = '❌'
            status_text = 'Ошибка конвертации'
            status_class = 'error'
        else:
            status_icon = '🔄'
            status_text = 'Конвертация в процессе'
            status_class = 'processing'
        
        # Информация об исходной дорожке
        src_channels = source_track.get('channels', 6)
        src_codec = source_track.get('codec', 'unknown').upper()
        
        # Информация о целевой дорожке
        tgt_channels = target_track.get('channels', 2) if target_track else 2
        tgt_codec = target_track.get('codec', 'AAC').upper() if target_track else 'AAC'
        
        # Загружаем шаблон
        template_path = self.templates_dir / "conversion_template.html"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            return template.format(
                status_class=status_class,
                status_icon=status_icon,
                status_text=status_text,
                filename=filename,
                src_channels=src_channels,
                src_codec=src_codec,
                tgt_channels=tgt_channels,
                tgt_codec=tgt_codec,
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M')
            )
        
        # Fallback к встроенному HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body>
            <div class="card">
                <div class="header {status_class}">
                    <h1 class="title">{status_icon} {status_text}</h1>
                </div>
                <div class="content">
                    <div class="file-name">{filename}</div>
                    <div class="conversion-flow">
                        <div class="track-box source">
                            <div class="track-title">Исходная дорожка</div>
                            <div class="track-info">
                                <span class="channels">{src_channels}ch</span>
                                <span class="codec">{src_codec}</span>
                            </div>
                        </div>
                        <div class="arrow">→</div>
                        <div class="track-box target">
                            <div class="track-title">Результат</div>
                            <div class="track-info">
                                <span class="channels">{tgt_channels}ch</span>
                                <span class="codec">{tgt_codec}</span>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="footer">
                    <span class="timestamp">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _create_summary_html(self, summary_info: Dict) -> str:
        """Создание HTML для сводной карточки"""
        stats = summary_info.get('stats', {})
        recent_files = summary_info.get('recent_files', [])
        is_startup = summary_info.get('startup', False)
        
        title = "🚀 Мониторинг запущен" if is_startup else "📊 Сводка по директории"
        
        # Статистика
        total_files = stats.get('total_files', 0)
        processed_files = stats.get('processed_files', 0)
        pending_files = stats.get('pending_files', 0)
        error_files = stats.get('error_files', 0)
        
        # Дополнительная информация для запуска
        startup_info = ""
        if is_startup:
            directory = summary_info.get('directory', '')
            interval = summary_info.get('interval', 0)
            if len(directory) > 50:
                directory = "..." + directory[-47:]
            startup_info = f"""
            <div class="startup-info">
                <div class="detail">📁 {directory}</div>
                <div class="detail">⏱ Интервал: {interval}с</div>
            </div>
            """
        
        # Список файлов
        files_html = ""
        files_title = "📁 Файлы в директории:" if is_startup else "📁 Последние файлы:"
        display_count = 6 if is_startup else 5
        
        for file_info in recent_files[:display_count]:
            filename = file_info.get('name', 'Неизвестно')
            if len(filename) > 40:
                filename = filename[:37] + "..."
            
            status = file_info.get('status', 'unknown')
            status_emoji = {
                'processed': '✅',
                'pending': '⏳',
                'error': '❌'
            }.get(status, '❓')
            
            files_html += f"""
            <div class="file-item {status}">
                <span class="status-icon">{status_emoji}</span>
                <span class="filename">{filename}</span>
            </div>
            """
        
        if len(recent_files) > display_count:
            files_html += f'<div class="more-files">... и еще {len(recent_files) - display_count} файлов</div>'
        
        # Загружаем шаблон
        template_path = self.templates_dir / "summary_template.html"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            return template.format(
                title=title,
                startup_info=startup_info,
                total_files=total_files,
                processed_files=processed_files,
                pending_files=pending_files,
                error_files=error_files,
                files_title=files_title,
                files_html=files_html,
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M')
            )
        
        # Fallback к встроенному HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body>
            <div class="card summary">
                <div class="header">
                    <h1 class="title">{title}</h1>
                </div>
                <div class="content">
                    {startup_info}
                    <div class="stats-grid">
                        <div class="stat-item">
                            <div class="stat-number">{total_files}</div>
                            <div class="stat-label">Всего файлов</div>
                        </div>
                        <div class="stat-item success">
                            <div class="stat-number">{processed_files}</div>
                            <div class="stat-label">Обработано</div>
                        </div>
                        <div class="stat-item warning">
                            <div class="stat-number">{pending_files}</div>
                            <div class="stat-label">Ожидает</div>
                        </div>
                        <div class="stat-item error">
                            <div class="stat-number">{error_files}</div>
                            <div class="stat-label">Ошибок</div>
                        </div>
                    </div>
                    <div class="files-section">
                        <h3>{files_title}</h3>
                        <div class="files-list">
                            {files_html}
                        </div>
                    </div>
                </div>
                <div class="footer">
                    <span class="timestamp">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _load_css(self) -> str:
        """Загрузка CSS из файла или возврат встроенных стилей"""
        css_path = self.templates_dir / "card_styles.css"
        if css_path.exists():
            try:
                with open(css_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Не удалось загрузить CSS файл: {e}")
        
        # Fallback к встроенным стилям
        return self._get_embedded_css()
    
    def _get_embedded_css(self) -> str:
        """Встроенные CSS стили"""
        return """
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%);
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .card {
            background: #313244;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            overflow: hidden;
            width: 100%;
            max-width: 560px;
        }
        
        .header {
            background: linear-gradient(135deg, #89b4fa 0%, #74c7ec 100%);
            padding: 20px;
            text-align: center;
        }
        
        .header.success {
            background: linear-gradient(135deg, #a6e3a1 0%, #94e2d5 100%);
        }
        
        .header.error {
            background: linear-gradient(135deg, #f38ba8 0%, #eba0ac 100%);
        }
        
        .header.processing {
            background: linear-gradient(135deg, #f9e2af 0%, #fab387 100%);
        }
        
        .title {
            color: #1e1e2e;
            font-size: 18px;
            font-weight: 600;
            margin: 0;
        }
        
        .content {
            padding: 24px;
        }
        
        .file-name {
            font-size: 16px;
            font-weight: 500;
            color: #cdd6f4;
            margin-bottom: 16px;
            text-align: center;
        }
        
        .file-details {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            justify-content: center;
        }
        
        .detail {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
        }
        
        .label {
            font-size: 12px;
            color: #9399b2;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .value {
            font-size: 14px;
            color: #cdd6f4;
            font-weight: 500;
        }
        
        .audio-section h3 {
            color: #cba6f7;
            font-size: 14px;
            margin-bottom: 12px;
            font-weight: 500;
        }
        
        .audio-tracks {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .audio-track {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 12px;
            border-radius: 8px;
            background: #45475a;
        }
        
        .audio-track.stereo {
            border-left: 3px solid #a6e3a1;
        }
        
        .audio-track.surround {
            border-left: 3px solid #f9e2af;
        }
        
        .audio-track.other {
            border-left: 3px solid #9399b2;
        }
        
        .channels {
            background: #585b70;
            color: #cdd6f4;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            min-width: 35px;
            text-align: center;
        }
        
        .language, .codec {
            font-size: 12px;
            color: #bac2de;
        }
        
        .conversion-flow {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            margin: 20px 0;
        }
        
        .track-box {
            background: #45475a;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            flex: 1;
            max-width: 140px;
        }
        
        .track-box.source {
            border: 2px solid #f9e2af;
        }
        
        .track-box.target {
            border: 2px solid #a6e3a1;
        }
        
        .track-title {
            font-size: 11px;
            color: #9399b2;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .track-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        
        .arrow {
            font-size: 24px;
            color: #89b4fa;
            font-weight: bold;
        }
        
        .startup-info {
            background: #45475a;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .startup-info .detail {
            color: #bac2de;
            font-size: 13px;
            margin: 4px 0;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        
        .stat-item {
            background: #45475a;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            border-top: 3px solid #585b70;
        }
        
        .stat-item.success {
            border-top-color: #a6e3a1;
        }
        
        .stat-item.warning {
            border-top-color: #f9e2af;
        }
        
        .stat-item.error {
            border-top-color: #f38ba8;
        }
        
        .stat-number {
            font-size: 18px;
            font-weight: 600;
            color: #cdd6f4;
            margin-bottom: 4px;
        }
        
        .stat-label {
            font-size: 10px;
            color: #9399b2;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .files-section h3 {
            color: #cba6f7;
            font-size: 14px;
            margin-bottom: 12px;
            font-weight: 500;
        }
        
        .files-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        
        .file-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-radius: 6px;
            background: #45475a;
        }
        
        .file-item.processed {
            border-left: 3px solid #a6e3a1;
        }
        
        .file-item.pending {
            border-left: 3px solid #f9e2af;
        }
        
        .file-item.error {
            border-left: 3px solid #f38ba8;
        }
        
        .status-icon {
            font-size: 14px;
        }
        
        .filename {
            font-size: 12px;
            color: #bac2de;
            flex: 1;
        }
        
        .more-tracks, .more-files {
            text-align: center;
            font-size: 11px;
            color: #9399b2;
            font-style: italic;
            margin-top: 8px;
        }
        
        .footer {
            background: #45475a;
            padding: 12px 20px;
            text-align: right;
        }
        
        .timestamp {
            font-size: 11px;
            color: #9399b2;
        }
        """
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def cleanup_temp_files(self, max_age_hours: int = 24):
        """Очистка временных файлов"""
        try:
            current_time = datetime.now()
            for file_path in self.temp_dir.glob("*.png"):
                file_age = current_time - datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_age.total_seconds() > max_age_hours * 3600:
                    file_path.unlink()
                    logger.debug(f"Удален временный файл: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка очистки временных файлов: {e}")
