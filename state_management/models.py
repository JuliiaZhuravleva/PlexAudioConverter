#!/usr/bin/env python3
"""
State Management Models - Модели данных для управления состояниями
FileEntry и GroupEntry - основные сущности системы учёта файлов
"""

import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, Union, List
from .enums import (
    IntegrityStatus, ProcessedStatus, PairStatus, IntegrityMode, 
    GroupProcessedStatus, validate_integrity_transition, 
    validate_processed_transition, validate_pair_transition
)


@dataclass
class FileEntry:
    """Единица учёта файла на ФС"""
    
    # Основные поля
    id: Optional[int] = None
    path: str = ""
    group_id: str = ""
    is_stereo: bool = False
    
    # Метаданные файла
    size_bytes: int = 0
    mtime: int = 0  # epoch seconds
    first_seen_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    stable_since: Optional[int] = None  # время, с которого размер не менялся
    next_check_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    
    # Статусы и результаты проверок
    integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN
    integrity_score: Optional[float] = None  # 0..1, доля читаемости/надёжности
    integrity_mode_used: Optional[IntegrityMode] = None
    integrity_fail_count: int = 0
    
    # Статус обработки
    processed_status: ProcessedStatus = ProcessedStatus.NEW
    has_en2: Optional[bool] = None  # есть ли английская 2.0 дорожка
    
    # Дополнительные поля
    last_error: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    updated_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))

    def __post_init__(self):
        """Валидация данных после создания"""
        if not self.path:
            raise ValueError("path не может быть пустым")
        
        # Нормализуем путь
        self.path = str(Path(self.path).resolve())
        
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
                         stable_threshold_sec: int = 30) -> bool:
        """
        Обновляет статистику файла (размер, время модификации)
        Возвращает True если файл изменился
        """
        changed = False
        now = int(datetime.now().timestamp())
        
        if self.size_bytes != size_bytes or self.mtime != mtime:
            self.size_bytes = size_bytes
            self.mtime = mtime
            # Полный сброс всех статусов - файл изменился, начинаем заново
            self.stable_since = None
            self.integrity_status = IntegrityStatus.UNKNOWN
            self.integrity_score = None
            self.integrity_mode_used = None
            self.integrity_fail_count = 0
            self.processed_status = ProcessedStatus.NEW
            self.has_en2 = None
            self.last_error = None
            self.next_check_at = now + 1  # проверим через секунду
            self.updated_at = now
            changed = True
        elif self.stable_since is None and (now - mtime >= stable_threshold_sec):
            # Файл не менялся достаточно долго - считаем стабильным
            self.stable_since = mtime  # устанавливаем момент последней модификации
            self.next_check_at = now  # можно проверять целостность
            self.updated_at = now
        
        return changed

    def is_due_for_check(self, current_time: Optional[int] = None) -> bool:
        """Готов ли файл к проверке"""
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        return self.next_check_at <= current_time

    def schedule_next_check(self, delay_seconds: int):
        """Планирует следующую проверку через delay_seconds"""
        now = int(datetime.now().timestamp())
        self.next_check_at = now + delay_seconds
        self.updated_at = now

    def is_stable(self, min_stable_sec: int = 30) -> bool:
        """Является ли файл стабильным (не меняется достаточно долго)"""
        if self.stable_since is None:
            return False
        now = int(datetime.now().timestamp())
        return (now - self.stable_since) >= min_stable_sec

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
    
    entry = FileEntry(
        path=str(path),
        group_id=group_id,
        is_stereo=is_stereo,
        size_bytes=stat.st_size,
        mtime=int(stat.st_mtime)
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