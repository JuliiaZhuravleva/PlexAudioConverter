"""
Video Integrity Checker Module

Использует FFmpeg/FFprobe для определения целостности и завершенности видеофайлов.
Особенно полезно для торрент-загрузок, где файл может быть частично доступен.
"""

import subprocess
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VideoIntegrityStatus(Enum):
    """Статус целостности видеофайла"""
    COMPLETE = "complete"
    INCOMPLETE = "incomplete" 
    CORRUPTED = "corrupted"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"


@dataclass
class VideoIntegrityInfo:
    """Информация о целостности видеофайла"""
    status: VideoIntegrityStatus
    duration: Optional[float] = None
    expected_duration: Optional[float] = None
    readable_duration: Optional[float] = None
    frame_count: Optional[int] = None
    expected_frame_count: Optional[int] = None
    file_size: int = 0
    has_valid_header: bool = False
    has_valid_footer: bool = False
    error_message: str = ""
    detection_method: str = ""


class VideoIntegrityChecker:
    """Проверка целостности видеофайлов с помощью FFmpeg"""
    
    def __init__(self, ffprobe_path: str = "ffprobe", ffmpeg_path: str = "ffmpeg"):
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_path = ffmpeg_path
        
    def check_video_integrity(self, file_path: Path) -> VideoIntegrityInfo:
        """Комплексная проверка целостности видеофайла"""
        
        info = VideoIntegrityInfo(
            status=VideoIntegrityStatus.UNKNOWN,
            file_size=file_path.stat().st_size if file_path.exists() else 0
        )
        
        if not file_path.exists():
            info.status = VideoIntegrityStatus.UNREADABLE
            info.error_message = "File does not exist"
            return info
            
        # Метод 1: Базовая проверка метаданных
        metadata_result = self._check_metadata(file_path)
        if metadata_result:
            info.duration = metadata_result.get('duration')
            info.frame_count = metadata_result.get('frame_count')
            info.has_valid_header = True
            info.detection_method = "metadata_check"
        else:
            info.status = VideoIntegrityStatus.UNREADABLE
            info.error_message = "Cannot read video metadata"
            return info
            
        # Метод 2: Проверка читаемости всего файла
        readable_duration = self._check_readable_duration(file_path)
        info.readable_duration = readable_duration
        
        # Метод 3: Анализ целостности
        integrity_status = self._analyze_integrity(info)
        info.status = integrity_status
        
        return info
    
    def _check_metadata(self, file_path: Path) -> Optional[Dict]:
        """Получение базовых метаданных файла"""
        try:
            cmd = [
                self.ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(file_path)
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if result.returncode != 0:
                logger.debug(f"FFprobe failed for {file_path}: {result.stderr}")
                return None
                
            data = json.loads(result.stdout)
            
            # Извлекаем информацию о видеопотоке
            video_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                    break
                    
            if not video_stream:
                return None
                
            duration = None
            if 'duration' in video_stream:
                duration = float(video_stream['duration'])
            elif 'duration' in data.get('format', {}):
                duration = float(data['format']['duration'])
                
            frame_count = None
            if 'nb_frames' in video_stream:
                frame_count = int(video_stream['nb_frames'])
                
            return {
                'duration': duration,
                'frame_count': frame_count,
                'codec': video_stream.get('codec_name'),
                'width': video_stream.get('width'),
                'height': video_stream.get('height')
            }
            
        except Exception as e:
            logger.debug(f"Error checking metadata for {file_path}: {e}")
            return None
    
    def _check_readable_duration(self, file_path: Path) -> Optional[float]:
        """Проверка, сколько секунд файла реально читается"""
        try:
            # Используем ffmpeg для декодирования файла в null
            # Это покажет, до какого момента файл читается без ошибок
            cmd = [
                self.ffmpeg_path,
                '-v', 'error',
                '-i', str(file_path),
                '-f', 'null',
                '-t', '10',  # Проверяем первые 10 секунд для быстроты
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            # Если команда выполнилась успешно, файл читается
            if result.returncode == 0:
                return 10.0  # Первые 10 секунд читаются нормально
                
            # Анализируем ошибки для определения проблем
            stderr = result.stderr.lower()
            if 'invalid data found' in stderr or 'end of file' in stderr:
                # Файл обрывается - пытаемся определить где
                return self._find_readable_end(file_path)
                
            return None
            
        except Exception as e:
            logger.debug(f"Error checking readable duration for {file_path}: {e}")
            return None
    
    def _find_readable_end(self, file_path: Path) -> Optional[float]:
        """Находит последнюю читаемую секунду файла"""
        try:
            # Бинарный поиск читаемой длительности
            # Сначала получаем заявленную длительность
            metadata = self._check_metadata(file_path)
            if not metadata or not metadata.get('duration'):
                return None
                
            total_duration = metadata['duration']
            
            # Проверяем середину файла
            mid_point = total_duration / 2
            
            cmd = [
                self.ffmpeg_path,
                '-v', 'error',
                '-ss', str(mid_point),
                '-i', str(file_path),
                '-t', '1',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Середина читается - файл скорее всего полный
                return total_duration
            else:
                # Середина не читается - файл неполный
                # Возвращаем примерную оценку
                return min(mid_point, total_duration * 0.3)
                
        except Exception as e:
            logger.debug(f"Error finding readable end for {file_path}: {e}")
            return None
    
    def _analyze_integrity(self, info: VideoIntegrityInfo) -> VideoIntegrityStatus:
        """Анализ целостности на основе собранной информации"""
        
        # Если нет базовой информации - файл нечитаемый
        if not info.duration:
            return VideoIntegrityStatus.UNREADABLE
            
        # Если нет информации о читаемости - считаем неизвестным
        if info.readable_duration is None:
            return VideoIntegrityStatus.UNKNOWN
            
        # Если читается менее 50% заявленной длительности - неполный
        readable_ratio = info.readable_duration / info.duration
        
        if readable_ratio < 0.5:
            info.detection_method = f"readable_ratio: {readable_ratio:.2f}"
            return VideoIntegrityStatus.INCOMPLETE
            
        # Если читается менее 90% - возможно неполный
        elif readable_ratio < 0.9:
            info.detection_method = f"readable_ratio: {readable_ratio:.2f} (suspicious)"
            return VideoIntegrityStatus.INCOMPLETE
            
        # Если читается почти все - скорее всего полный
        else:
            info.detection_method = f"readable_ratio: {readable_ratio:.2f}"
            return VideoIntegrityStatus.COMPLETE
    
    def quick_integrity_check(self, file_path: Path) -> bool:
        """Быстрая проверка - файл полный или нет"""
        try:
            # Простая проверка - можем ли прочитать метаданные
            metadata = self._check_metadata(file_path)
            if not metadata:
                return False
                
            # Проверяем, можем ли прочитать начало и конец файла
            duration = metadata.get('duration')
            if not duration or duration < 60:  # Слишком короткий файл
                return False
                
            # Проверяем последние 10 секунд файла
            cmd = [
                self.ffmpeg_path,
                '-v', 'error',
                '-ss', str(duration - 10),
                '-i', str(file_path),
                '-t', '5',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.debug(f"Error in quick integrity check for {file_path}: {e}")
            return False
    
    def is_video_complete(self, file_path: Path) -> Tuple[bool, str]:
        """
        Определяет, завершен ли видеофайл
        Возвращает (is_complete, reason)
        """
        try:
            if not file_path.exists():
                return False, "file_not_found"
                
            # Быстрая проверка
            if self.quick_integrity_check(file_path):
                return True, "quick_check_passed"
                
            # Полная проверка
            integrity_info = self.check_video_integrity(file_path)
            
            if integrity_info.status == VideoIntegrityStatus.COMPLETE:
                return True, f"complete: {integrity_info.detection_method}"
            elif integrity_info.status == VideoIntegrityStatus.INCOMPLETE:
                return False, f"incomplete: {integrity_info.detection_method}"
            else:
                return False, f"status: {integrity_info.status.value}"
                
        except Exception as e:
            logger.error(f"Error checking video completion for {file_path}: {e}")
            return False, f"error: {str(e)}"


# Глобальный экземпляр для удобства использования
_global_checker = None

def get_video_checker() -> VideoIntegrityChecker:
    """Получить глобальный экземпляр проверки видео"""
    global _global_checker
    if _global_checker is None:
        _global_checker = VideoIntegrityChecker()
    return _global_checker

def is_video_file_complete(file_path: Path) -> Tuple[bool, str]:
    """Удобная функция для проверки завершенности видеофайла"""
    return get_video_checker().is_video_complete(file_path)
