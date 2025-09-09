#!/usr/bin/env python3
"""
State Management Models - Модели данных для управления состояниями
FileEntry и GroupEntry - основные сущности системы учёта файлов
"""

import json
import hashlib
import os
import platform
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, Union, List
from .enums import (
    IntegrityStatus, ProcessedStatus, PairStatus, IntegrityMode, 
    GroupProcessedStatus, validate_integrity_transition, 
    validate_processed_transition, validate_pair_transition
)
from .time_provider import TimeSource, get_time_source


@dataclass
class FileEntry:
    """Единица учёта файла на ФС"""
    
    # Основные поля
    id: Optional[int] = None
    path: str = ""
    group_id: str = ""
    is_stereo: bool = False
    
    # File identity fields for rename tracking
    file_device: Optional[int] = None  # Device ID (POSIX) or Volume serial (Windows)
    file_inode: Optional[int] = None   # Inode (POSIX) or File index (Windows)
    file_identity: Optional[str] = None  # Fallback: hash-based identity for tests
    
    # Метаданные файла
    size_bytes: int = 0
    mtime: int = 0  # epoch seconds (wall time)
    first_seen_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    stable_since: Optional[int] = None  # время, с которого размер не менялся (wall time, legacy)
    next_check_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    
    # Monotonic time fields for deterministic stability decisions
    last_change_at: Optional[float] = None  # monotonic time of last size/mtime change
    stable_since_mono: Optional[float] = None  # monotonic time when stability was armed
    
    # Статусы и результаты проверок
    integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN
    integrity_score: Optional[float] = None  # 0..1, доля читаемости/надёжности
    integrity_mode_used: Optional[IntegrityMode] = None
    integrity_fail_count: int = 0
    
    # Статус обработки
    processed_status: ProcessedStatus = ProcessedStatus.NEW
    has_en2: Optional[bool] = None  # есть ли английская 2.0 дорожка
    
    # Lease management for PENDING protection
    pending_owner: Optional[str] = None  # Worker/process ID that owns the lease
    pending_expires_at: Optional[float] = None  # Monotonic time when lease expires
    
    # Дополнительные поля
    last_error: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    updated_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))

    def __post_init__(self):
        """Валидация данных после создания"""
        if not self.path:
            raise ValueError("path не может быть пустым")
        
        # Нормализуем путь с учетом платформозависимости  
        from .platform_utils import normalize_path_for_storage
        self.path = normalize_path_for_storage(self.path)
        
        # Валидация диапазонов
        if self.integrity_score is not None:
            if not (0.0 <= self.integrity_score <= 1.0):
                raise ValueError("integrity_score должен быть в диапазоне 0..1")
        
        if self.integrity_fail_count < 0:
            self.integrity_fail_count = 0

    def update_integrity_status(self, status: IntegrityStatus, 
                               score: Optional[float] = None,
                               mode: Optional[IntegrityMode] = None,
                               error: Optional[str] = None) -> bool:
        """
        Обновляет статус целостности с валидацией переходов
        Возвращает True если переход был выполнен
        """
        if not validate_integrity_transition(self.integrity_status, status):
            raise ValueError(
                f"Некорректный переход integrity_status: {self.integrity_status} -> {status}"
            )
        
        self.integrity_status = status
        self.updated_at = int(datetime.now().timestamp())
        
        if score is not None:
            if not (0.0 <= score <= 1.0):
                raise ValueError("integrity_score должен быть в диапазоне 0..1")
            self.integrity_score = score
        
        if mode is not None:
            self.integrity_mode_used = mode
        
        if status in {IntegrityStatus.INCOMPLETE, IntegrityStatus.ERROR}:
            self.integrity_fail_count += 1
            if error:
                self.last_error = error
        elif status == IntegrityStatus.COMPLETE:
            # Сбрасываем счётчик ошибок при успешной проверке
            self.integrity_fail_count = 0
            self.last_error = None
        
        return True

    def update_processed_status(self, status: ProcessedStatus, 
                               has_en2: Optional[bool] = None,
                               error: Optional[str] = None) -> bool:
        """
        Обновляет статус обработки с валидацией переходов
        Возвращает True если переход был выполнен
        """
        if not validate_processed_transition(self.processed_status, status):
            raise ValueError(
                f"Некорректный переход processed_status: {self.processed_status} -> {status}"
            )
        
        self.processed_status = status
        self.updated_at = int(datetime.now().timestamp())
        
        if has_en2 is not None:
            self.has_en2 = has_en2
        
        if status == ProcessedStatus.CONVERT_FAILED and error:
            self.last_error = error
        elif status in {ProcessedStatus.CONVERTED, ProcessedStatus.SKIPPED_HAS_EN2}:
            self.last_error = None
        
        return True

    def update_file_stats(self, size_bytes: int, mtime: int, 
                         stable_threshold_sec: int = 30, 
                         time_source: TimeSource = None) -> bool:
        """
        Обновляет статистику файла (размер, время модификации) с использованием monotonic time
        Возвращает True если файл изменился
        
        Args:
            size_bytes: новый размер файла
            mtime: новое время модификации файла (wall time)
            stable_threshold_sec: порог стабильности в секундах
            time_source: источник времени (по умолчанию - глобальный)
        """
        if time_source is None:
            time_source = get_time_source()
        
        changed = False
        now_wall = time_source.now_wall()
        now_mono = time_source.now_mono()
        
        if self.size_bytes != size_bytes or self.mtime != mtime:
            # Файл изменился - полный сброс состояния
            self.size_bytes = size_bytes
            self.mtime = mtime
            self.last_change_at = now_mono
            
            # Сброс всех статусов stability и integrity
            self.stable_since = None
            self.stable_since_mono = None
            self.integrity_status = IntegrityStatus.UNKNOWN
            self.integrity_score = None
            self.integrity_mode_used = None
            self.integrity_fail_count = 0
            self.processed_status = ProcessedStatus.NEW
            self.has_en2 = None
            self.last_error = None
            
            # Короткая задержка перед следующей проверкой
            self.next_check_at = int(now_wall + 2)  # проверим через 2 секунды
            self.updated_at = int(now_wall)
            changed = True
            
        elif self.last_change_at is None:
            # Миграция: устанавливаем last_change_at для существующих записей
            self.last_change_at = now_mono
            self.updated_at = int(now_wall)
            
        return changed

    def is_due_for_check(self, current_time: Optional[int] = None) -> bool:
        """Готов ли файл к проверке"""
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        return self.next_check_at <= current_time
    
    def is_quarantined(self, current_time: Optional[int] = None) -> bool:
        """
        Находится ли файл в карантине (quarantine state)
        
        Карантин = integrity_status в {INCOMPLETE, ERROR} И будущий next_check_at
        """
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        
        return (
            self.integrity_status in {IntegrityStatus.INCOMPLETE, IntegrityStatus.ERROR} and 
            self.next_check_at > current_time
        )

    def schedule_next_check(self, delay_seconds: int):
        """Планирует следующую проверку через delay_seconds"""
        now = int(datetime.now().timestamp())
        self.next_check_at = now + delay_seconds
        self.updated_at = now

    def is_stable(self, min_stable_sec: int = 30) -> bool:
        """Является ли файл стабильным (не меняется достаточно долго) - legacy wall time"""
        if self.stable_since is None:
            return False
        now = int(datetime.now().timestamp())
        return (now - self.stable_since) >= min_stable_sec
    
    def is_stable_mono(self, min_stable_sec: int = 30, time_source: TimeSource = None) -> bool:
        """Является ли файл стабильным по monotonic time (предпочтительный метод)"""
        if time_source is None:
            time_source = get_time_source()
        
        if self.stable_since_mono is None:
            return False
        
        now_mono = time_source.now_mono()
        return (now_mono - self.stable_since_mono) >= min_stable_sec
    
    def arm_stability(self, time_source: TimeSource = None) -> bool:
        """
        Проверить и активировать стабильность если файл достаточно долго не менялся
        
        Returns:
            True если стабильность была активирована в этом вызове
        """
        if time_source is None:
            time_source = get_time_source()
        
        now_mono = time_source.now_mono()
        
        # Уже стабилен
        if self.stable_since_mono is not None:
            return False
        
        # Нет информации о последнем изменении
        if self.last_change_at is None:
            return False
        
        # Проверяем, прошла ли секунда с последнего изменения (минимальная задержка)
        if (now_mono - self.last_change_at) >= 1.0:
            self.stable_since_mono = now_mono
            # Set legacy stable_since for backward compatibility
            self.stable_since = int(time_source.now_wall())
            self.updated_at = int(time_source.now_wall())
            return True
        
        return False
    
    def get_stability_due_time(self, stable_wait_sec: int, time_source: TimeSource = None) -> float:
        """
        Получить wall time когда файл будет готов к integrity проверке
        
        Returns:
            Wall time timestamp когда файл станет готов, или 0.0 если уже готов
        """
        if time_source is None:
            time_source = get_time_source()
        
        if self.stable_since_mono is None:
            # Еще не стабилен
            return time_source.now_wall() + stable_wait_sec
        
        elapsed_stable = time_source.now_mono() - self.stable_since_mono
        remaining = stable_wait_sec - elapsed_stable
        
        if remaining <= 0:
            return 0.0  # Уже готов
        
        return time_source.now_wall() + remaining

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для сериализации"""
        data = asdict(self)
        # Преобразуем enum'ы в строки
        data['integrity_status'] = self.integrity_status.value
        data['processed_status'] = self.processed_status.value
        if self.integrity_mode_used:
            data['integrity_mode_used'] = self.integrity_mode_used.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FileEntry':
        """Создание из словаря при десериализации"""
        # Преобразуем строки в enum'ы
        if 'integrity_status' in data:
            data['integrity_status'] = IntegrityStatus(data['integrity_status'])
        if 'processed_status' in data:
            data['processed_status'] = ProcessedStatus(data['processed_status'])
        if 'integrity_mode_used' in data and data['integrity_mode_used']:
            data['integrity_mode_used'] = IntegrityMode(data['integrity_mode_used'])
        
        return cls(**data)


@dataclass
class GroupEntry:
    """Логическая группа из original и .stereo файлов"""
    
    # Основные поля
    group_id: str = ""
    delete_original: bool = False  # слепок конфигурации на момент создания
    
    # Состояние группы
    original_present: bool = False
    stereo_present: bool = False
    pair_status: PairStatus = PairStatus.NONE
    processed_status: GroupProcessedStatus = GroupProcessedStatus.NEW
    
    # Метаданные
    first_seen_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    updated_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))

    def __post_init__(self):
        """Валидация данных после создания"""
        if not self.group_id:
            raise ValueError("group_id не может быть пустым")

    def update_presence(self, original_present: bool, stereo_present: bool) -> bool:
        """
        Обновляет информацию о присутствии файлов в группе
        Возвращает True если состояние изменилось
        """
        changed = False
        
        if self.original_present != original_present or self.stereo_present != stereo_present:
            self.original_present = original_present
            self.stereo_present = stereo_present
            self.updated_at = int(datetime.now().timestamp())
            changed = True
            
            # Обновляем статус группы
            new_pair_status = self._calculate_pair_status()
            if new_pair_status != self.pair_status:
                if validate_pair_transition(self.pair_status, new_pair_status):
                    self.pair_status = new_pair_status
                else:
                    raise ValueError(
                        f"Некорректный переход pair_status: {self.pair_status} -> {new_pair_status}"
                    )
        
        return changed

    def update_processed_status(self, status: GroupProcessedStatus) -> bool:
        """
        Обновляет статус обработки группы
        Возвращает True если статус изменился
        """
        if self.processed_status == status:
            return False
        
        self.processed_status = status
        self.updated_at = int(datetime.now().timestamp())
        return True

    def _calculate_pair_status(self) -> PairStatus:
        """Вычисляет статус группы на основе присутствия файлов"""
        if not self.original_present and not self.stereo_present:
            return PairStatus.NONE
        elif self.original_present and self.stereo_present:
            return PairStatus.PAIRED
        else:
            return PairStatus.WAITING_PAIR

    def is_complete(self) -> bool:
        """Является ли группа полной (согласно настройке delete_original)"""
        if self.delete_original:
            # При удалении оригинала достаточно одного .stereo файла
            return self.stereo_present
        else:
            # При сохранении оригинала нужны оба файла
            return self.pair_status == PairStatus.PAIRED

    def can_process(self) -> bool:
        """Может ли группа быть обработана"""
        return (self.processed_status == GroupProcessedStatus.NEW and 
                (self.original_present or self.stereo_present))

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для сериализации"""
        data = asdict(self)
        # Преобразуем enum'ы в строки
        data['pair_status'] = self.pair_status.value
        data['processed_status'] = self.processed_status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GroupEntry':
        """Создание из словаря при десериализации"""
        # Преобразуем строки в enum'ы
        if 'pair_status' in data:
            data['pair_status'] = PairStatus(data['pair_status'])
        if 'processed_status' in data:
            data['processed_status'] = GroupProcessedStatus(data['processed_status'])
        
        return cls(**data)


def normalize_group_id(file_path: Union[str, Path], use_parent_context: bool = True) -> tuple[str, bool]:
    """
    Нормализует group_id из пути к файлу
    
    Args:
        file_path: путь к файлу
        use_parent_context: добавлять ли контекст родительской папки для коллизий
    
    Returns:
        tuple[group_id, is_stereo]
    """
    path = Path(file_path)
    basename = path.stem  # имя файла без расширения
    
    # Проверяем, является ли файл stereo-версией
    is_stereo = basename.lower().endswith('.stereo')
    
    if is_stereo:
        # Убираем суффикс .stereo
        group_name = basename[:-7]  # убираем '.stereo'
    else:
        group_name = basename
    
    if use_parent_context:
        # Добавляем контекст родительской папки для избежания коллизий
        parent_name = path.parent.name
        parent_hash = hashlib.md5(str(path.parent).encode('utf-8')).hexdigest()[:8]
        group_id = f"{parent_hash}/{group_name}"
    else:
        group_id = group_name
    
    return group_id, is_stereo


def create_file_entry_from_path(file_path: Union[str, Path], 
                               delete_original: bool = False) -> FileEntry:
    """
    Создает FileEntry из пути к файлу
    
    Args:
        file_path: путь к файлу
        delete_original: режим удаления оригиналов
    
    Returns:
        FileEntry с заполненными основными полями
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")
    
    stat = path.stat()
    group_id, is_stereo = normalize_group_id(path)
    device, inode, identity = get_file_identity(path)
    
    from .platform_utils import normalize_path_for_storage
    
    entry = FileEntry(
        path=str(path),  # __post_init__ will handle normalization
        group_id=group_id,
        is_stereo=is_stereo,
        size_bytes=stat.st_size,
        mtime=int(stat.st_mtime),
        file_device=device,
        file_inode=inode,
        file_identity=identity
    )
    
    return entry


def create_group_entry(group_id: str, delete_original: bool = False) -> GroupEntry:
    """
    Создает GroupEntry для указанного group_id
    
    Args:
        group_id: идентификатор группы
        delete_original: режим удаления оригиналов
    
    Returns:
        GroupEntry с заполненными основными полями
    """
    return GroupEntry(
        group_id=group_id,
        delete_original=delete_original
    )


def get_file_identity(file_path: Union[str, Path]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Get file identity for rename tracking
    
    Returns:
        tuple[device, inode, fallback_identity]
        - device/inode for POSIX systems
        - None, None, hash_identity for tests/fallback
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return None, None, None
    
    try:
        stat = file_path.stat()
        
        if platform.system() != 'Windows':
            # POSIX: use device and inode
            return int(stat.st_dev), int(stat.st_ino), None
        else:
            # Windows: try to get file index and volume serial
            # For now, use fallback method since getting Windows file ID is complex
            fallback_identity = _get_fallback_identity(file_path, stat)
            return None, None, fallback_identity
            
    except (OSError, AttributeError):
        # Fallback to hash-based identity
        fallback_identity = _get_fallback_identity(file_path, None)
        return None, None, fallback_identity


def _get_fallback_identity(file_path: Path, stat: Optional[os.stat_result] = None) -> str:
    """
    Generate hash-based file identity for fallback/tests
    
    Uses only initial content to create a stable identity across renames and file modifications
    This ensures identity remains stable during download processes where size/mtime change
    """
    if stat is None:
        try:
            stat = file_path.stat()
        except OSError:
            return hashlib.md5(str(file_path).encode('utf-8')).hexdigest()
    
    # Use only the first chunk of content for stable identity
    # This remains stable even as file grows during download
    try:
        # Read first 4KB of file content for stable identity across file modifications
        with open(file_path, 'rb') as f:
            content_sample = f.read(4096)
        
        # If file is empty or very small, include the filename for uniqueness
        if len(content_sample) == 0:
            fallback = hashlib.md5(file_path.name.encode('utf-8')).hexdigest()
            return fallback
        
        # For stable identity during downloads, use only initial content
        # This remains stable across renames and file modifications
        # DO NOT include size, mtime, or path as they change during active downloads/renames
        content_hash = hashlib.md5(content_sample).hexdigest()
        return content_hash
        
    except (OSError, IOError):
        # Fallback to filename-based identity
        return hashlib.md5(file_path.name.encode('utf-8')).hexdigest()