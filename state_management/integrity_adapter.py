#!/usr/bin/env python3
"""
Integrity Adapter - Адаптер для интеграции с системой проверки целостности
Обеспечивает стабильный интерфейс для state_management независимо от изменений в core
"""

import logging
from pathlib import Path
from typing import Optional
from .enums import IntegrityStatus, IntegrityMode

logger = logging.getLogger(__name__)


class IntegrityAdapter:
    """Адаптер для интеграции с видео integrity checker"""
    
    def __init__(self, ffprobe_path: str = "ffprobe", ffmpeg_path: str = "ffmpeg"):
        self._ffprobe_path = ffprobe_path
        self._ffmpeg_path = ffmpeg_path
        self._checker = None
        self._init_checker()
    
    def _init_checker(self):
        """Инициализация checker с обработкой импорта"""
        import sys
        from pathlib import Path
        
        # Список вариантов импорта для максимальной совместимости
        import_variants = [
            # Вариант 1: core модуль (если есть в PYTHONPATH)
            ("core.video_integrity_checker", "VideoIntegrityChecker", "VideoIntegrityStatus"),
            # Вариант 2: прямой импорт из корневой директории
            ("video_integrity_checker", "VideoIntegrityChecker", "VideoIntegrityStatus"),
        ]
        
        # Добавляем родительскую директорию в PYTHONPATH
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))
        
        for module_name, checker_class, status_class in import_variants:
            try:
                module = __import__(module_name, fromlist=[checker_class, status_class])
                checker_cls = getattr(module, checker_class)
                status_cls = getattr(module, status_class)
                
                self._checker = checker_cls(
                    ffprobe_path=self._ffprobe_path,
                    ffmpeg_path=self._ffmpeg_path
                )
                self._VideoIntegrityStatus = status_cls
                logger.info(f"Video integrity checker initialized from {module_name}")
                return
                
            except (ImportError, AttributeError) as e:
                logger.debug(f"Failed to import from {module_name}: {e}")
                continue
        
        # Все варианты не сработали
        logger.warning("Video integrity checker not available - all import variants failed")
        logger.warning("Available: status will always be UNKNOWN, score will be None")
        self._checker = None
        self._VideoIntegrityStatus = None
    
    def check_video_integrity(self, file_path: str, mode: IntegrityMode = IntegrityMode.QUICK) -> tuple[IntegrityStatus, Optional[float]]:
        """
        Проверяет целостность видеофайла
        
        Args:
            file_path: путь к видеофайлу
            mode: режим проверки (QUICK или FULL)
        
        Returns:
            tuple[IntegrityStatus, score] где score в диапазоне 0..1 или None
        """
        if self._checker is None:
            logger.warning("Video integrity checker not available, returning UNKNOWN status")
            return IntegrityStatus.UNKNOWN, None
        
        try:
            # Выбираем метод в зависимости от режима
            if mode == IntegrityMode.QUICK:
                # Быстрая проверка
                result = self._checker.quick_integrity_check(file_path)
            else:
                # Полная проверка (FULL или AUTO)
                result = self._checker.check_video_integrity(file_path)
            
            # Конвертируем результат в наши enum'ы
            status = self._convert_status(result.status)
            
            # Вычисляем score на основе результатов
            score = self._calculate_score(result)
            
            return status, score
            
        except Exception as e:
            logger.error(f"Error checking video integrity for {file_path}: {e}")
            return IntegrityStatus.ERROR, None
    
    def _convert_status(self, external_status) -> IntegrityStatus:
        """Конвертирует статус из внешнего API в наш формат"""
        if self._VideoIntegrityStatus is None:
            return IntegrityStatus.UNKNOWN
        
        mapping = {
            self._VideoIntegrityStatus.COMPLETE: IntegrityStatus.COMPLETE,
            self._VideoIntegrityStatus.INCOMPLETE: IntegrityStatus.INCOMPLETE,
            self._VideoIntegrityStatus.CORRUPTED: IntegrityStatus.INCOMPLETE,
            self._VideoIntegrityStatus.UNREADABLE: IntegrityStatus.ERROR,
            self._VideoIntegrityStatus.UNKNOWN: IntegrityStatus.UNKNOWN,
        }
        
        return mapping.get(external_status, IntegrityStatus.UNKNOWN)
    
    def _calculate_score(self, result) -> Optional[float]:
        """Вычисляет score на основе результатов проверки"""
        try:
            if result.status == self._VideoIntegrityStatus.COMPLETE:
                return 1.0
            elif result.status == self._VideoIntegrityStatus.INCOMPLETE:
                # Если есть информация о длительности, используем её
                if result.duration and result.expected_duration:
                    return min(1.0, result.duration / result.expected_duration)
                else:
                    return 0.5  # частично читаемый файл
            else:
                return 0.0  # нечитаемый или повреждённый файл
        except Exception:
            return None
    
    def is_available(self) -> bool:
        """Проверяет доступность integrity checker"""
        return self._checker is not None


# Singleton instance для использования в state machine
_integrity_adapter: Optional[IntegrityAdapter] = None

def get_integrity_adapter(ffprobe_path: str = "ffprobe", ffmpeg_path: str = "ffmpeg") -> IntegrityAdapter:
    """Получает глобальный экземпляр адаптера"""
    global _integrity_adapter
    if _integrity_adapter is None:
        _integrity_adapter = IntegrityAdapter(ffprobe_path, ffmpeg_path)
    return _integrity_adapter