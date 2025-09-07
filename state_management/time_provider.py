#!/usr/bin/env python3
"""
Time Provider - Абстракция для источников времени
Обеспечивает детерминистичное поведение в тестах и продакшене
"""

import time
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Protocol
from dataclasses import dataclass


@dataclass
class FileStats:
    """Статистика файла"""
    size: int
    mtime: int  # Wall time (epoch seconds)
    
    
class TimeSource(ABC):
    """Абстрактный источник времени"""
    
    @abstractmethod
    def now_wall(self) -> float:
        """Текущее время стены (wall time) в секундах с эпохи Unix"""
        pass
    
    @abstractmethod
    def now_mono(self) -> float:
        """Монотонное время в секундах (не зависит от изменений системного времени)"""
        pass


class StatProvider(ABC):
    """Абстрактный провайдер статистики файлов"""
    
    @abstractmethod
    def stat(self, path: Path) -> FileStats:
        """Получить статистику файла"""
        pass
    
    @abstractmethod
    def exists(self, path: Path) -> bool:
        """Проверить существование файла"""
        pass


class SystemTimeSource(TimeSource):
    """Системный источник времени для продакшена"""
    
    def now_wall(self) -> float:
        """Unix timestamp (wall time)"""
        return time.time()
    
    def now_mono(self) -> float:
        """Monotonic time in seconds"""
        return time.monotonic()


class SystemStatProvider(StatProvider):
    """Системный провайдер статистики файлов для продакшена"""
    
    def stat(self, path: Path) -> FileStats:
        """Получить реальную статистику файла"""
        try:
            st = os.stat(path)
            return FileStats(
                size=st.st_size,
                mtime=int(st.st_mtime)
            )
        except (OSError, IOError) as e:
            raise FileNotFoundError(f"Cannot stat file {path}") from e
    
    def exists(self, path: Path) -> bool:
        """Проверить реальное существование файла"""
        return path.exists()


class FakeTimeSource(TimeSource):
    """Поддельный источник времени для тестов"""
    
    def __init__(self, initial_wall: float = None, initial_mono: float = None):
        """
        Инициализация поддельного времени
        
        Args:
            initial_wall: начальное wall time (по умолчанию - текущее время)
            initial_mono: начальное monotonic time (по умолчанию - 0)
        """
        self._wall_time = initial_wall or time.time()
        self._mono_time = initial_mono or 0.0
    
    def now_wall(self) -> float:
        return self._wall_time
    
    def now_mono(self) -> float:
        return self._mono_time
    
    def advance(self, seconds: float):
        """Продвинуть время вперед на указанное количество секунд"""
        self._wall_time += seconds
        self._mono_time += seconds
    
    def set_wall(self, wall_time: float):
        """Установить конкретное wall time (симуляция изменения системного времени)"""
        self._wall_time = wall_time
    
    def set_mono(self, mono_time: float):
        """Установить конкретное monotonic time"""
        self._mono_time = mono_time


class FakeStatProvider(StatProvider):
    """Поддельный провайдер статистики для тестов"""
    
    def __init__(self, time_source: TimeSource):
        """
        Инициализация поддельного статистического провайдера
        
        Args:
            time_source: источник времени для mtime
        """
        self.time_source = time_source
        self._file_stats: Dict[str, FileStats] = {}
        self._existing_files: set[str] = set()
    
    def stat(self, path: Path) -> FileStats:
        """Получить поддельную статистику файла"""
        path_str = str(path.resolve())
        
        if path_str not in self._existing_files:
            raise FileNotFoundError(f"Fake file not found: {path}")
        
        if path_str in self._file_stats:
            return self._file_stats[path_str]
        
        # Если файл существует, но нет статистики, создаем дефолтную
        return FileStats(size=0, mtime=int(self.time_source.now_wall()))
    
    def exists(self, path: Path) -> bool:
        """Проверить поддельное существование файла"""
        return str(path.resolve()) in self._existing_files
    
    def set_file_stats(self, path: Path, size: int, mtime: int = None):
        """Установить статистику для поддельного файла"""
        path_str = str(path.resolve())
        if mtime is None:
            mtime = int(self.time_source.now_wall())
        
        self._file_stats[path_str] = FileStats(size=size, mtime=mtime)
        self._existing_files.add(path_str)
    
    def update_file_size(self, path: Path, new_size: int):
        """Обновить размер файла (симуляция записи)"""
        path_str = str(path.resolve())
        if path_str not in self._existing_files:
            raise FileNotFoundError(f"Cannot update non-existent fake file: {path}")
        
        current_stats = self._file_stats.get(path_str, FileStats(size=0, mtime=0))
        self._file_stats[path_str] = FileStats(
            size=new_size,
            mtime=int(self.time_source.now_wall())
        )
    
    def remove_file(self, path: Path):
        """Удалить поддельный файл"""
        path_str = str(path.resolve())
        self._existing_files.discard(path_str)
        self._file_stats.pop(path_str, None)


# Глобальные экземпляры по умолчанию
_default_time_source = SystemTimeSource()
_default_stat_provider = SystemStatProvider()


def get_time_source() -> TimeSource:
    """Получить текущий глобальный источник времени"""
    return _default_time_source


def get_stat_provider() -> StatProvider:
    """Получить текущий глобальный провайдер статистики"""
    return _default_stat_provider


def set_time_source(source: TimeSource):
    """Установить глобальный источник времени (для тестов)"""
    global _default_time_source
    _default_time_source = source


def set_stat_provider(provider: StatProvider):
    """Установить глобальный провайдер статистики (для тестов)"""
    global _default_stat_provider
    _default_stat_provider = provider


def reset_to_system():
    """Сбросить к системным провайдерам (после тестов)"""
    global _default_time_source, _default_stat_provider
    _default_time_source = SystemTimeSource()
    _default_stat_provider = SystemStatProvider()