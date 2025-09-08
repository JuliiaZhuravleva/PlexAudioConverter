#!/usr/bin/env python3
"""
State Store - Хранилище состояний на базе SQLite
Устойчивое, дешёвое по ресурсам state-хранилище с транзакциями и индексацией
"""

import sqlite3
import json
import logging
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from contextlib import contextmanager
import threading
from dataclasses import asdict

from .models import FileEntry, GroupEntry
from .enums import IntegrityStatus, ProcessedStatus, PairStatus, GroupProcessedStatus

logger = logging.getLogger(__name__)


class StateStoreError(Exception):
    """Базовая ошибка StateStore"""
    pass


class StateStore:
    """SQLite-хранилище для управления состояниями файлов и групп"""
    
    # Lease management constants
    LEASE_TIMEOUT_SECONDS = 300.0  # 5 minutes default lease timeout
    _worker_id_cache = None  # Cache for worker ID
    
    # SQL-схемы
    SCHEMA_FILES = """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            group_id TEXT NOT NULL,
            is_stereo INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            first_seen_at INTEGER NOT NULL,
            stable_since INTEGER,
            next_check_at INTEGER NOT NULL,
            integrity_status TEXT NOT NULL,
            integrity_score REAL,
            integrity_mode_used TEXT,
            integrity_fail_count INTEGER NOT NULL DEFAULT 0,
            processed_status TEXT NOT NULL,
            has_en2 INTEGER,
            last_error TEXT,
            extra TEXT,
            updated_at INTEGER NOT NULL,
            last_change_at REAL,
            stable_since_mono REAL,
            file_device INTEGER,
            file_inode INTEGER,
            file_identity TEXT,
            pending_owner TEXT,
            pending_expires_at REAL
        )
    """
    
    SCHEMA_GROUPS = """
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            delete_original INTEGER NOT NULL,
            original_present INTEGER NOT NULL,
            stereo_present INTEGER NOT NULL,
            pair_status TEXT NOT NULL,
            processed_status TEXT NOT NULL,
            first_seen_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """
    
    INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_files_next ON files(next_check_at)",
        "CREATE INDEX IF NOT EXISTS idx_files_group ON files(group_id)",
        "CREATE INDEX IF NOT EXISTS idx_files_identity ON files(file_device, file_inode)",
        "CREATE INDEX IF NOT EXISTS idx_files_identity_str ON files(file_identity)",
        "CREATE INDEX IF NOT EXISTS idx_files_status ON files(processed_status)",
        "CREATE INDEX IF NOT EXISTS idx_files_integrity ON files(integrity_status)",
        "CREATE INDEX IF NOT EXISTS idx_groups_processed ON groups(processed_status)",
        "CREATE INDEX IF NOT EXISTS idx_groups_pair ON groups(pair_status)"
    ]

    def __init__(self, db_path: Union[str, Path] = "state.db"):
        """
        Инициализация хранилища
        
        Args:
            db_path: путь к файлу базы данных
        """
        self.db_path_str = str(db_path)
        self.db_path = Path(db_path) if db_path != ":memory:" else None
        self._lock = threading.RLock()
        self._memory_conn = None  # Persistent connection for :memory: databases
        
        # Создаем директорию если нужно (только для файловых БД)
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Инициализируем БД
        self._init_database()
        
        # Выполняем миграцию для новых полей monotonic time
        self._migrate_monotonic_fields()
        
        # Выполняем миграцию для полей file identity
        self._migrate_identity_fields()
        
        # Выполняем миграцию для полей lease management
        self._migrate_lease_fields()
        
        # Создаем индексы после всех миграций
        self._create_indexes()
        
        logger.info(f"StateStore инициализирован: {self.db_path_str}")

    def _init_database(self):
        """Инициализация структуры БД"""
        with self._get_connection() as conn:
            # Создаем таблицы
            conn.execute(self.SCHEMA_FILES)
            conn.execute(self.SCHEMA_GROUPS)
            
            conn.commit()

    def _create_indexes(self):
        """Создание индексов после миграций"""
        with self._get_connection() as conn:
            for index_sql in self.INDEXES:
                try:
                    conn.execute(index_sql)
                except sqlite3.OperationalError as e:
                    if "already exists" not in str(e):
                        logger.warning(f"Не удалось создать индекс: {e}")
            
            conn.commit()

    def _migrate_monotonic_fields(self):
        """Миграция для добавления полей monotonic time"""
        with self._get_connection() as conn:
            # Проверяем, существуют ли новые поля
            cursor = conn.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # Добавляем новые поля если их нет
            if 'last_change_at' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN last_change_at REAL")
                logger.info("Добавлено поле last_change_at в таблицу files")
            
            if 'stable_since_mono' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN stable_since_mono REAL")
                logger.info("Добавлено поле stable_since_mono в таблицу files")
            
            conn.commit()

    def _migrate_identity_fields(self):
        """Миграция для добавления полей file identity"""
        with self._get_connection() as conn:
            # Проверяем, существуют ли новые поля
            cursor = conn.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # Добавляем новые поля если их нет
            if 'file_device' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN file_device INTEGER")
                logger.info("Добавлено поле file_device в таблицу files")
            
            if 'file_inode' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN file_inode INTEGER")
                logger.info("Добавлено поле file_inode в таблицу files")
                
            if 'file_identity' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN file_identity TEXT")
                logger.info("Добавлено поле file_identity в таблицу files")
            
            # Создаем индексы для новых полей если их нет
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_files_identity ON files(file_device, file_inode)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_files_identity_str ON files(file_identity)")
            except Exception as e:
                logger.warning(f"Could not create identity indexes: {e}")
            
            conn.commit()

    def _migrate_lease_fields(self):
        """Миграция для добавления полей lease management"""
        with self._get_connection() as conn:
            # Проверяем, существуют ли новые поля
            cursor = conn.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # Добавляем новые поля если их нет
            if 'pending_owner' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN pending_owner TEXT")
                logger.info("Добавлено поле pending_owner в таблицу files")
            
            if 'pending_expires_at' not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN pending_expires_at REAL")
                logger.info("Добавлено поле pending_expires_at в таблицу files")
            
            # Создаем индекс для эффективности lease queries
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_files_pending ON files(pending_owner, pending_expires_at)")
                logger.debug("Создан индекс idx_files_pending для таблицы files")
            except sqlite3.OperationalError:
                pass  # Индекс уже существует
            
            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Получение подключения к БД с блокировкой"""
        with self._lock:
            if self.db_path_str == ":memory:":
                # For in-memory databases, reuse the same connection
                if self._memory_conn is None:
                    self._memory_conn = sqlite3.connect(
                        self.db_path_str,
                        timeout=30.0,
                        check_same_thread=False
                    )
                    self._memory_conn.row_factory = sqlite3.Row
                yield self._memory_conn
            else:
                # For file databases, create new connections each time
                conn = sqlite3.connect(
                    self.db_path_str,
                    timeout=30.0,
                    check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                finally:
                    conn.close()

    def _row_to_file_entry(self, row: sqlite3.Row) -> FileEntry:
        """Преобразование строки БД в FileEntry"""
        data = dict(row)
        
        # Преобразуем булевы поля
        data['is_stereo'] = bool(data['is_stereo'])
        if data['has_en2'] is not None:
            data['has_en2'] = bool(data['has_en2'])
        
        # Преобразуем enum'ы
        data['integrity_status'] = IntegrityStatus(data['integrity_status'])
        data['processed_status'] = ProcessedStatus(data['processed_status'])
        
        if data['integrity_mode_used']:
            from .enums import IntegrityMode
            data['integrity_mode_used'] = IntegrityMode(data['integrity_mode_used'])
        
        # Парсим JSON
        if data['extra']:
            data['extra'] = json.loads(data['extra'])
        
        return FileEntry.from_dict(data)

    def _row_to_group_entry(self, row: sqlite3.Row) -> GroupEntry:
        """Преобразование строки БД в GroupEntry"""
        data = dict(row)
        
        # Преобразуем булевы поля
        data['delete_original'] = bool(data['delete_original'])
        data['original_present'] = bool(data['original_present'])
        data['stereo_present'] = bool(data['stereo_present'])
        
        # Преобразуем enum'ы
        data['pair_status'] = PairStatus(data['pair_status'])
        data['processed_status'] = GroupProcessedStatus(data['processed_status'])
        
        return GroupEntry.from_dict(data)

    def _file_entry_to_values(self, entry: FileEntry) -> Tuple:
        """Преобразование FileEntry в кортеж значений для SQL"""
        extra_json = json.dumps(entry.extra) if entry.extra else None
        integrity_mode = entry.integrity_mode_used.value if entry.integrity_mode_used else None
        
        return (
            entry.path,
            entry.group_id,
            int(entry.is_stereo),
            entry.size_bytes,
            entry.mtime,
            entry.first_seen_at,
            entry.stable_since,
            entry.next_check_at,
            entry.integrity_status.value,
            entry.integrity_score,
            integrity_mode,
            entry.integrity_fail_count,
            entry.processed_status.value,
            int(entry.has_en2) if entry.has_en2 is not None else None,
            entry.last_error,
            extra_json,
            entry.updated_at,
            entry.last_change_at,
            entry.stable_since_mono,
            entry.file_device,
            entry.file_inode,
            entry.file_identity,
            entry.pending_owner,
            entry.pending_expires_at
        )

    def _group_entry_to_values(self, entry: GroupEntry) -> Tuple:
        """Преобразование GroupEntry в кортеж значений для SQL"""
        return (
            entry.group_id,
            int(entry.delete_original),
            int(entry.original_present),
            int(entry.stereo_present),
            entry.pair_status.value,
            entry.processed_status.value,
            entry.first_seen_at,
            entry.updated_at
        )

    # === Методы для работы с файлами ===

    def get_file(self, path: Union[str, Path]) -> Optional[FileEntry]:
        """Получение файла по пути"""
        path_str = str(Path(path).resolve())
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM files WHERE path = ?",
                (path_str,)
            )
            row = cursor.fetchone()
            
            if row:
                return self._row_to_file_entry(row)
            return None

    def get_file_by_id(self, file_id: int) -> Optional[FileEntry]:
        """Получение файла по ID"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM files WHERE id = ?",
                (file_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return self._row_to_file_entry(row)
            return None

    def upsert_file(self, entry=None, **kwargs) -> FileEntry:
        """
        Обновление или создание файла
        
        Args:
            entry: FileEntry object (new API)
            **kwargs: path, size_bytes, mtime, etc. (legacy API for tests)
            
        Returns:
            Обновленный FileEntry с заполненным ID
        """
        from .models import FileEntry
        from .enums import IntegrityStatus, ProcessedStatus
        import time
        
        # Backward compatibility: if called with kwargs instead of FileEntry
        if entry is None and kwargs:
            from .models import normalize_group_id
            
            # Auto-generate group_id if not provided
            file_path = kwargs.get('path')
            if file_path and 'group_id' not in kwargs:
                group_id, is_stereo_detected = normalize_group_id(file_path)
                kwargs['group_id'] = group_id
                # Use detected is_stereo if not explicitly provided
                if 'is_stereo' not in kwargs:
                    kwargs['is_stereo'] = is_stereo_detected
                    
            # Create FileEntry from kwargs
            entry = FileEntry(
                path=kwargs.get('path'),
                size_bytes=kwargs.get('size_bytes', 0),
                mtime=int(kwargs.get('mtime', time.time())),
                integrity_status=kwargs.get('integrity_status', IntegrityStatus.UNKNOWN),
                processed_status=kwargs.get('processed_status', ProcessedStatus.NEW),
                first_seen_at=int(kwargs.get('first_seen_at', time.time())),
                next_check_at=int(kwargs.get('next_check_at', time.time())),
                is_stereo=kwargs.get('is_stereo', False),
                group_id=kwargs.get('group_id'),
                integrity_score=kwargs.get('integrity_score'),
                integrity_mode_used=kwargs.get('integrity_mode_used'),
                integrity_fail_count=kwargs.get('integrity_fail_count', 0),
                has_en2=kwargs.get('has_en2'),
                last_error=kwargs.get('last_error'),
                extra=kwargs.get('extra', {}),
                updated_at=int(kwargs.get('updated_at', time.time())),
                last_change_at=int(kwargs.get('last_change_at', time.time())),
                stable_since=kwargs.get('stable_since'),
                stable_since_mono=kwargs.get('stable_since_mono')
            )
        elif entry is None:
            raise ValueError("Either 'entry' parameter or keyword arguments must be provided")
            
        # Now proceed with the original logic
        with self._get_connection() as conn:
            try:
                if entry.id is None:
                    # Upsert - создание или обновление на основе пути
                    cursor = conn.execute("""
                        INSERT INTO files (
                            path, group_id, is_stereo, size_bytes, mtime,
                            first_seen_at, stable_since, next_check_at,
                            integrity_status, integrity_score, integrity_mode_used,
                            integrity_fail_count, processed_status, has_en2,
                            last_error, extra, updated_at, last_change_at, stable_since_mono,
                            file_device, file_inode, file_identity, pending_owner, pending_expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            group_id = excluded.group_id,
                            is_stereo = excluded.is_stereo,
                            size_bytes = excluded.size_bytes,
                            mtime = excluded.mtime,
                            stable_since = excluded.stable_since,
                            next_check_at = excluded.next_check_at,
                            integrity_status = excluded.integrity_status,
                            integrity_score = excluded.integrity_score,
                            integrity_mode_used = excluded.integrity_mode_used,
                            integrity_fail_count = excluded.integrity_fail_count,
                            processed_status = excluded.processed_status,
                            has_en2 = excluded.has_en2,
                            last_error = excluded.last_error,
                            extra = excluded.extra,
                            updated_at = excluded.updated_at,
                            last_change_at = excluded.last_change_at,
                            stable_since_mono = excluded.stable_since_mono,
                            file_device = excluded.file_device,
                            file_inode = excluded.file_inode,
                            file_identity = excluded.file_identity,
                            pending_owner = excluded.pending_owner,
                            pending_expires_at = excluded.pending_expires_at
                    """, self._file_entry_to_values(entry))
                    
                    # Получаем ID записи (или новой, или обновленной)
                    entry.id = cursor.lastrowid or conn.execute(
                        "SELECT id FROM files WHERE path = ?", (entry.path,)
                    ).fetchone()[0]
                else:
                    # Обновление существующего файла по ID
                    conn.execute("""
                        UPDATE files SET
                            path = ?, group_id = ?, is_stereo = ?, size_bytes = ?, mtime = ?,
                            first_seen_at = ?, stable_since = ?, next_check_at = ?,
                            integrity_status = ?, integrity_score = ?, integrity_mode_used = ?,
                            integrity_fail_count = ?, processed_status = ?, has_en2 = ?,
                            last_error = ?, extra = ?, updated_at = ?, last_change_at = ?, stable_since_mono = ?,
                            file_device = ?, file_inode = ?, file_identity = ?,
                            pending_owner = ?, pending_expires_at = ?
                        WHERE id = ?
                    """, self._file_entry_to_values(entry) + (entry.id,))
                
                conn.commit()
                logger.debug(f"Файл сохранён: {entry.path} (ID: {entry.id})")
                return entry
                
            except sqlite3.IntegrityError as e:
                conn.rollback()
                raise StateStoreError(f"Ошибка сохранения файла {entry.path}: {e}")

    def update_file_size(self, file_path: str, new_size: int, new_mtime: float) -> bool:
        """
        Backward compatibility method: Update only file size and modification time
        
        Args:
            file_path: путь к файлу
            new_size: новый размер файла
            new_mtime: новое время модификации
            
        Returns:
            True if successful, False otherwise
        """
        import time
        try:
            with self._get_connection() as conn:
                # Update только size и mtime, сбросить stable_since если размер изменился
                cursor = conn.execute("""
                    UPDATE files 
                    SET size_bytes = ?, 
                        mtime = ?, 
                        stable_since = CASE 
                            WHEN size_bytes != ? THEN NULL 
                            ELSE stable_since 
                        END,
                        updated_at = ?,
                        last_change_at = CASE
                            WHEN size_bytes != ? THEN ?
                            ELSE last_change_at
                        END
                    WHERE path = ?
                """, (new_size, int(new_mtime), new_size, int(time.time()), new_size, int(time.time()), file_path))
                
                conn.commit()
                rows_affected = cursor.rowcount
                
                if rows_affected > 0:
                    logger.debug(f"Обновлен размер файла: {file_path} -> {new_size} bytes")
                    return True
                else:
                    logger.warning(f"Файл не найден для обновления размера: {file_path}")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка обновления размера файла {file_path}: {e}")
            return False

    def check_stability_and_schedule(self, file_path: str, stable_wait_sec: int = 30) -> bool:
        """
        Backward compatibility method: Check file stability and schedule for processing if stable
        
        Args:
            file_path: путь к файлу
            stable_wait_sec: время ожидания стабильности (по умолчанию 30 секунд)
            
        Returns:
            True if file became stable, False otherwise
        """
        import time
        try:
            with self._get_connection() as conn:
                # Get current file info
                cursor = conn.execute("""
                    SELECT id, size_bytes, last_change_at, stable_since, next_check_at
                    FROM files WHERE path = ?
                """, (file_path,))
                
                row = cursor.fetchone()
                if not row:
                    logger.warning(f"Файл не найден для проверки стабильности: {file_path}")
                    return False
                
                file_id, size_bytes, last_change_at, stable_since, next_check_at = row
                current_time = int(time.time())
                
                # If already stable, nothing to do
                if stable_since is not None:
                    return True
                
                # Check if enough time has passed since last change
                time_since_change = current_time - (last_change_at or current_time)
                
                if time_since_change >= stable_wait_sec:
                    # Mark as stable and schedule for immediate processing
                    # Set next_check_at to current_time - 10 to ensure it's definitely due
                    conn.execute("""
                        UPDATE files 
                        SET stable_since = ?,
                            next_check_at = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (current_time, current_time - 10, current_time, file_id))
                    
                    conn.commit()
                    logger.debug(f"Файл стабилизировался и запланирован: {file_path}")
                    return True
                else:
                    logger.debug(f"Файл еще не стабилен: {file_path} (осталось {stable_wait_sec - time_since_change}s)")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка проверки стабильности файла {file_path}: {e}")
            return False

    def set_integrity_status(self, file_path: str, status: IntegrityStatus) -> bool:
        """
        Backward compatibility method: Set integrity status for a file
        
        Args:
            file_path: путь к файлу
            status: новый статус целостности
            
        Returns:
            True если файл найден и обновлен, False иначе
        """
        try:
            with self._get_connection() as conn:
                current_time = int(datetime.now().timestamp())
                
                cursor = conn.execute("""
                    UPDATE files 
                    SET integrity_status = ?,
                        updated_at = ?
                    WHERE path = ?
                """, (status.value, current_time, file_path))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.debug(f"Обновлен статус целостности для {file_path}: {status.value}")
                    return True
                else:
                    logger.warning(f"Файл не найден для обновления статуса: {file_path}")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка обновления статуса целостности для {file_path}: {e}")
            return False
            
    def transition_integrity_status(self, file_path: Union[str, Path], from_status: IntegrityStatus, 
                                   to_status: IntegrityStatus, next_check_at: Optional[int] = None,
                                   score: Optional[float] = None, error: Optional[str] = None,
                                   fail_count_increment: int = 0) -> bool:
        """
        Атомарный переход статуса целостности с проверкой исходного состояния
        
        Args:
            file_path: путь к файлу
            from_status: ожидаемый текущий статус
            to_status: новый статус
            next_check_at: время следующей проверки
            score: оценка целостности
            error: сообщение об ошибке
            fail_count_increment: на сколько увеличить счетчик неудач
        
        Returns:
            True если переход выполнен успешно
        """
        from .metrics import get_metrics
        path_str = str(Path(file_path).resolve())
        current_time = int(datetime.now().timestamp())
        metrics = get_metrics()
        
        with self._get_connection() as conn:
            try:
                # Атомарная проверка и обновление
                if fail_count_increment > 0:
                    cursor = conn.execute("""
                        UPDATE files SET 
                            integrity_status = ?,
                            integrity_score = ?,
                            last_error = ?,
                            next_check_at = COALESCE(?, next_check_at),
                            integrity_fail_count = integrity_fail_count + ?,
                            updated_at = ?
                        WHERE path = ? AND integrity_status = ?
                    """, (
                        to_status.value,
                        score,
                        error,
                        next_check_at,
                        fail_count_increment,
                        current_time,
                        path_str,
                        from_status.value
                    ))
                else:
                    cursor = conn.execute("""
                        UPDATE files SET 
                            integrity_status = ?,
                            integrity_score = ?,
                            last_error = ?,
                            next_check_at = COALESCE(?, next_check_at),
                            updated_at = ?
                        WHERE path = ? AND integrity_status = ?
                    """, (
                        to_status.value,
                        score,
                        error,
                        next_check_at,
                        current_time,
                        path_str,
                        from_status.value
                    ))
                
                success = cursor.rowcount > 0
                if success:
                    conn.commit()
                    # Записываем метрику перехода
                    metrics.increment(f"files_transitions_total", {
                        'from': from_status.value,
                        'to': to_status.value
                    })
                    logger.debug(f"Статус перешел {from_status.value} -> {to_status.value}: {Path(file_path).name}")
                else:
                    logger.warning(f"Не удался переход {from_status.value} -> {to_status.value}: {Path(file_path).name}")
                
                return success
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Ошибка перехода статуса для {file_path}: {e}")
                return False

    def get_due_files(self, current_time: Optional[int] = None, limit: int = 100) -> List[FileEntry]:
        """
        Получение файлов, готовых к проверке с учетом lease protection
        
        Args:
            current_time: текущее время (по умолчанию - сейчас)
            limit: максимальное количество файлов
        
        Returns:
            Список FileEntry, отсортированный по next_check_at
        """
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        
        # Get current monotonic time for lease expiration check
        from .time_provider import get_time_source
        time_source = get_time_source()
        current_mono = time_source.now_mono()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files 
                WHERE next_check_at <= ? 
                AND (
                    integrity_status != 'PENDING' 
                    OR (
                        integrity_status = 'PENDING' 
                        AND (
                            pending_owner IS NULL 
                            OR pending_expires_at IS NULL 
                            OR pending_expires_at <= ?
                        )
                    )
                )
                ORDER BY next_check_at ASC
                LIMIT ?
            """, (current_time, current_mono, limit))
            
            files = []
            for row in cursor.fetchall():
                files.append(self._row_to_file_entry(row))
            
            # Clean up any expired leases we found
            if files:
                expired_count = 0
                for file_entry in files:
                    if (file_entry.integrity_status == IntegrityStatus.PENDING and
                        file_entry.pending_expires_at is not None and 
                        file_entry.pending_expires_at <= current_mono):
                        # This lease is expired, clean it up
                        file_entry.pending_owner = None
                        file_entry.pending_expires_at = None
                        file_entry.integrity_status = IntegrityStatus.UNKNOWN
                        expired_count += 1
                
                if expired_count > 0:
                    logger.debug(f"Found {expired_count} expired leases in due files query")
            
            return files

    def find_file_by_identity(self, device: Optional[int] = None, 
                             inode: Optional[int] = None, 
                             identity: Optional[str] = None) -> Optional[FileEntry]:
        """
        Find file by its identity (device/inode or fallback identity)
        
        Args:
            device: Device ID (POSIX)
            inode: Inode number (POSIX)
            identity: Fallback identity string
            
        Returns:
            FileEntry if found, None otherwise
        """
        with self._get_connection() as conn:
            if device is not None and inode is not None:
                # Use device/inode for POSIX
                cursor = conn.execute("""
                    SELECT * FROM files 
                    WHERE file_device = ? AND file_inode = ?
                    LIMIT 1
                """, (device, inode))
            elif identity is not None:
                # Use fallback identity
                cursor = conn.execute("""
                    SELECT * FROM files 
                    WHERE file_identity = ?
                    LIMIT 1
                """, (identity,))
            else:
                return None
            
            row = cursor.fetchone()
            return self._row_to_file_entry(row) if row else None

    def handle_rename(self, old_path: str, new_path: str) -> Optional[FileEntry]:
        """
        Handle file rename - update path while preserving identity and state
        
        Args:
            old_path: Previous file path
            new_path: New file path
            
        Returns:
            Updated FileEntry if successful, None if file not found
        """
        from .models import normalize_group_id, get_file_identity
        
        # Get identity of new path
        new_device, new_inode, new_identity = get_file_identity(new_path)
        
        # Try to find existing entry by identity first
        existing_entry = None
        if new_device is not None and new_inode is not None:
            existing_entry = self.find_file_by_identity(device=new_device, inode=new_inode)
        elif new_identity is not None:
            existing_entry = self.find_file_by_identity(identity=new_identity)
        
        # If not found by identity, try to find by old path
        if existing_entry is None:
            existing_entry = self.get_file(old_path)
        
        if existing_entry is None:
            logger.warning(f"Could not find file to rename from {old_path} to {new_path}")
            return None
        
        # Update the entry with new path and group_id
        new_group_id, new_is_stereo = normalize_group_id(new_path)
        
        with self._get_connection() as conn:
            try:
                # Update the file record - preserving all state except path-related fields
                # Per task requirements: "stability windows follow identity, not path"
                cursor = conn.execute("""
                    UPDATE files 
                    SET path = ?,
                        group_id = ?,
                        is_stereo = ?,
                        file_device = ?,
                        file_inode = ?,
                        file_identity = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    new_path, 
                    new_group_id, 
                    int(new_is_stereo),
                    new_device,
                    new_inode, 
                    new_identity,
                    int(datetime.now().timestamp()),
                    existing_entry.id
                ))
                
                if cursor.rowcount == 0:
                    logger.error(f"Failed to update file record for rename {old_path} -> {new_path}")
                    return None
                
                conn.commit()
                logger.info(f"File renamed: {old_path} -> {new_path} (ID: {existing_entry.id})")
                
                # Return updated entry
                return self.get_file(new_path)
                
            except Exception as e:
                logger.error(f"Error handling rename {old_path} -> {new_path}: {e}")
                conn.rollback()
                return None
    
    def get_quarantined_files_count(self, current_time: Optional[int] = None) -> int:
        """
        Получение количества файлов в карантине
        
        Карантин = файлы с неудачной проверкой целостности и будущим next_check_at
        """
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM files 
                WHERE integrity_status IN ('INCOMPLETE', 'ERROR') 
                AND next_check_at > ?
            """, (current_time,))
            
            return cursor.fetchone()[0]

    def get_files_by_group(self, group_id: str) -> List[FileEntry]:
        """Получение всех файлов группы"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM files WHERE group_id = ? ORDER BY is_stereo ASC",
                (group_id,)
            )
            
            files = []
            for row in cursor.fetchall():
                files.append(self._row_to_file_entry(row))
            
            return files

    def delete_file(self, path: Union[str, Path]) -> bool:
        """Удаление файла из хранилища"""
        path_str = str(Path(path).resolve())
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM files WHERE path = ?",
                (path_str,)
            )
            conn.commit()
            
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug(f"Файл удалён из хранилища: {path_str}")
            
            return deleted

    # === Методы для работы с группами ===

    def get_group(self, group_id: str) -> Optional[GroupEntry]:
        """Получение группы по ID"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM groups WHERE group_id = ?",
                (group_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return self._row_to_group_entry(row)
            return None

    def upsert_group(self, entry: GroupEntry) -> GroupEntry:
        """Обновление или создание группы"""
        with self._get_connection() as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO groups (
                        group_id, delete_original, original_present, stereo_present,
                        pair_status, processed_status, first_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, self._group_entry_to_values(entry))
                
                conn.commit()
                logger.debug(f"Группа сохранена: {entry.group_id}")
                return entry
                
            except sqlite3.IntegrityError as e:
                conn.rollback()
                raise StateStoreError(f"Ошибка сохранения группы {entry.group_id}: {e}")

    def update_group_presence(self, group_id: str, delete_original: bool = False) -> GroupEntry:
        """
        Обновляет информацию о присутствии файлов в группе
        
        Args:
            group_id: идентификатор группы
            delete_original: режим удаления оригиналов
        
        Returns:
            Обновленная GroupEntry
        """
        # Получаем текущие файлы группы
        files = self.get_files_by_group(group_id)
        
        original_present = any(not f.is_stereo for f in files)
        stereo_present = any(f.is_stereo for f in files)
        
        # Получаем или создаем группу
        group = self.get_group(group_id)
        if group is None:
            from .models import create_group_entry
            group = create_group_entry(group_id, delete_original)
        
        # Обновляем присутствие
        group.update_presence(original_present, stereo_present)
        
        # Проверяем, готова ли группа к финализации
        self._check_group_finalization(group, files)
        
        # Сохраняем
        return self.upsert_group(group)

    def _check_group_finalization(self, group: GroupEntry, files: List[FileEntry]):
        """
        Проверяет и устанавливает финальный статус GROUP_PROCESSED для группы
        
        Правила финализации:
        - При delete_original=true: достаточно наличия .stereo файла в финальном статусе
        - При delete_original=false: нужна пара (original + .stereo) и оба в финальных статусах
        """
        from .enums import GroupProcessedStatus
        
        # Уже финализирована
        if group.processed_status == GroupProcessedStatus.GROUP_PROCESSED:
            return
            
        # Получаем файлы по типам
        original_files = [f for f in files if not f.is_stereo]
        stereo_files = [f for f in files if f.is_stereo]
        
        # Определяем финальные статусы обработки
        final_statuses = {ProcessedStatus.SKIPPED_HAS_EN2, ProcessedStatus.CONVERTED, ProcessedStatus.IGNORED}
        
        if group.delete_original:
            # Режим удаления оригинала: достаточно stereo-файла в финальном статусе
            stereo_processed = any(f.processed_status in final_statuses for f in stereo_files)
            
            if stereo_processed:
                group.update_processed_status(GroupProcessedStatus.GROUP_PROCESSED)
                self._finalize_group_files(files, final_statuses)
                logger.info(f"Группа финализирована (delete_original=true): {group.group_id}")
        else:
            # Режим сохранения оригинала: специальная логика для разных случаев
            original_processed = any(f.processed_status in final_statuses for f in original_files)
            stereo_processed = any(f.processed_status in final_statuses for f in stereo_files)
            
            # Проверяем, есть ли файлы со статусом SKIPPED_HAS_EN2
            has_skipped_en2 = any(f.processed_status == ProcessedStatus.SKIPPED_HAS_EN2 for f in original_files)
            
            should_finalize = False
            reason = ""
            
            if has_skipped_en2 and original_processed:
                # Если оригинал уже имеет EN2 дорожку, конвертация не нужна - группа готова
                should_finalize = True
                reason = "SKIPPED_HAS_EN2"
            elif group.pair_status == PairStatus.PAIRED and original_processed and stereo_processed:
                # Стандартная пара: оригинал + stereo, оба обработаны
                should_finalize = True
                reason = "delete_original=false"
            
            if should_finalize:
                group.update_processed_status(GroupProcessedStatus.GROUP_PROCESSED)
                self._finalize_group_files(files, final_statuses)
                logger.info(f"Группа финализирована ({reason}): {group.group_id}")
    
    def _finalize_group_files(self, files: List[FileEntry], final_statuses: set):
        """
        Переводит все файлы группы в финальное состояние и отключает от планировщика
        """
        from datetime import datetime
        
        processed_count = 0
        
        for file_entry in files:
            if file_entry.processed_status in final_statuses:
                # Переводим в GROUP_PROCESSED и отключаем от планировщика
                file_entry.update_processed_status(ProcessedStatus.GROUP_PROCESSED)
                
                # Устанавливаем next_check_at в далекое будущее (файл больше не нужно проверять)
                file_entry.next_check_at = int(datetime.now().timestamp()) + 365 * 24 * 3600  # +1 год
                
                # Сохраняем изменения
                self.upsert_file(file_entry)
                processed_count += 1
        
        if processed_count > 0:
            logger.debug(f"Финализировано файлов в группе: {processed_count}")

    def delete_group(self, group_id: str) -> bool:
        """Удаление группы из хранилища"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM groups WHERE group_id = ?",
                (group_id,)
            )
            conn.commit()
            
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug(f"Группа удалена из хранилища: {group_id}")
            
            return deleted

    # === Служебные методы ===

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики хранилища"""
        with self._get_connection() as conn:
            stats = {}
            
            # Общие счетчики файлов
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            stats['total_files'] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM groups")
            stats['total_groups'] = cursor.fetchone()[0]
            
            # Статистика по статусам целостности
            cursor = conn.execute("""
                SELECT integrity_status, COUNT(*) 
                FROM files 
                GROUP BY integrity_status
            """)
            stats['integrity_status'] = dict(cursor.fetchall())
            
            # Статистика по статусам обработки
            cursor = conn.execute("""
                SELECT processed_status, COUNT(*) 
                FROM files 
                GROUP BY processed_status
            """)
            stats['processed_status'] = dict(cursor.fetchall())
            
            # Файлы готовые к проверке
            current_time = int(datetime.now().timestamp())
            cursor = conn.execute("""
                SELECT COUNT(*) FROM files WHERE next_check_at <= ?
            """, (current_time,))
            stats['due_files'] = cursor.fetchone()[0]
            
            return stats

    def cleanup_old_entries(self, max_entries: int = 5000, 
                           keep_processed_days: int = 30) -> int:
        """
        Очистка старых записей (GC)
        
        Args:
            max_entries: максимальное количество записей
            keep_processed_days: сколько дней хранить обработанные файлы
        
        Returns:
            Количество удаленных записей
        """
        deleted_count = 0
        current_time = int(datetime.now().timestamp())
        cutoff_time = current_time - (keep_processed_days * 24 * 60 * 60)
        
        with self._get_connection() as conn:
            # Удаляем старые обработанные файлы
            cursor = conn.execute("""
                DELETE FROM files 
                WHERE processed_status IN ('CONVERTED', 'SKIPPED_HAS_EN2', 'GROUP_PROCESSED') 
                AND updated_at < ?
            """, (cutoff_time,))
            deleted_count += cursor.rowcount
            
            # Если все еще слишком много записей, удаляем самые старые
            cursor = conn.execute("SELECT COUNT(*) FROM files")
            total_files = cursor.fetchone()[0]
            
            if total_files > max_entries:
                excess = total_files - max_entries
                cursor = conn.execute("""
                    DELETE FROM files 
                    WHERE id IN (
                        SELECT id FROM files 
                        ORDER BY updated_at ASC 
                        LIMIT ?
                    )
                """, (excess,))
                deleted_count += cursor.rowcount
            
            # Удаляем группы без файлов
            cursor = conn.execute("""
                DELETE FROM groups 
                WHERE group_id NOT IN (SELECT DISTINCT group_id FROM files)
            """)
            deleted_groups = cursor.rowcount
            
            conn.commit()
            
            if deleted_count > 0 or deleted_groups > 0:
                logger.info(f"GC: удалено {deleted_count} файлов, {deleted_groups} групп")
        
        return deleted_count

    def backup_database(self, backup_path: Union[str, Path]) -> bool:
        """Создание резервной копии БД"""
        try:
            if self.db_path_str == ":memory:":
                logger.warning("Нельзя создать резервную копию in-memory базы данных")
                return False
            
            import shutil
            backup_path = Path(backup_path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(self.db_path_str, backup_path)
            logger.info(f"Резервная копия создана: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка создания резервной копии: {e}")
            return False

    def vacuum_database(self) -> bool:
        """Оптимизация БД (VACUUM)"""
        try:
            with self._get_connection() as conn:
                conn.execute("VACUUM")
                conn.commit()
            
            logger.info("База данных оптимизирована (VACUUM)")
            return True
        except Exception as e:
            logger.error(f"Ошибка оптимизации БД: {e}")
            return False

    # === Lease Management Methods ===

    @classmethod
    def _get_worker_id(cls) -> str:
        """Generate a unique worker ID for lease ownership"""
        if cls._worker_id_cache is None:
            # Use process ID + thread ID + random UUID for uniqueness
            pid = os.getpid()
            tid = threading.get_ident()
            uid = str(uuid.uuid4())[:8]
            cls._worker_id_cache = f"worker-{pid}-{tid}-{uid}"
        return cls._worker_id_cache

    def acquire_lease(self, file_entry: FileEntry, lease_timeout_seconds: Optional[float] = None) -> bool:
        """
        Acquire a lease for PENDING protection
        
        Args:
            file_entry: FileEntry to acquire lease for
            lease_timeout_seconds: Custom lease timeout (default: LEASE_TIMEOUT_SECONDS)
            
        Returns:
            True if lease acquired successfully, False otherwise
        """
        if lease_timeout_seconds is None:
            lease_timeout_seconds = self.LEASE_TIMEOUT_SECONDS
            
        worker_id = self._get_worker_id()
        
        # Use monotonic time for lease expiration to avoid clock changes
        from .time_provider import get_time_source
        time_source = get_time_source()
        expires_at = time_source.now_mono() + lease_timeout_seconds
        
        with self._get_connection() as conn:
            try:
                # Atomically acquire lease only if no active lease exists
                cursor = conn.execute("""
                    UPDATE files 
                    SET pending_owner = ?, 
                        pending_expires_at = ?,
                        integrity_status = 'PENDING',
                        updated_at = ?
                    WHERE id = ? 
                    AND (pending_owner IS NULL 
                         OR pending_expires_at IS NULL 
                         OR pending_expires_at <= ?)
                """, (
                    worker_id,
                    expires_at, 
                    int(time_source.now_wall()),
                    file_entry.id,
                    time_source.now_mono()  # Current time for expiration check
                ))
                
                conn.commit()
                success = cursor.rowcount > 0
                
                if success:
                    # Update the FileEntry object
                    file_entry.pending_owner = worker_id
                    file_entry.pending_expires_at = expires_at
                    file_entry.integrity_status = IntegrityStatus.PENDING
                    logger.debug(f"Acquired lease for file {file_entry.path} (worker: {worker_id})")
                else:
                    logger.debug(f"Failed to acquire lease for file {file_entry.path} (already leased)")
                
                return success
                
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Error acquiring lease for file {file_entry.path}: {e}")
                return False

    def release_lease(self, file_entry: FileEntry, new_integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN) -> bool:
        """
        Release a lease and update integrity status
        
        Args:
            file_entry: FileEntry to release lease for  
            new_integrity_status: New integrity status after processing
            
        Returns:
            True if lease released successfully, False otherwise
        """
        worker_id = self._get_worker_id()
        
        with self._get_connection() as conn:
            try:
                # Only release if we own the lease
                cursor = conn.execute("""
                    UPDATE files 
                    SET pending_owner = NULL,
                        pending_expires_at = NULL,
                        integrity_status = ?,
                        updated_at = ?
                    WHERE id = ? AND pending_owner = ?
                """, (
                    new_integrity_status.value,
                    int(datetime.now().timestamp()),
                    file_entry.id,
                    worker_id
                ))
                
                conn.commit()
                success = cursor.rowcount > 0
                
                if success:
                    # Update the FileEntry object
                    file_entry.pending_owner = None
                    file_entry.pending_expires_at = None
                    file_entry.integrity_status = new_integrity_status
                    logger.debug(f"Released lease for file {file_entry.path} (worker: {worker_id})")
                else:
                    logger.warning(f"Failed to release lease for file {file_entry.path} (not owned by {worker_id})")
                
                return success
                
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Error releasing lease for file {file_entry.path}: {e}")
                return False

    def cleanup_expired_leases(self) -> int:
        """
        Clean up expired leases
        
        Returns:
            Number of expired leases cleaned up
        """
        from .time_provider import get_time_source
        time_source = get_time_source()
        current_mono = time_source.now_mono()
        
        with self._get_connection() as conn:
            try:
                cursor = conn.execute("""
                    UPDATE files 
                    SET pending_owner = NULL,
                        pending_expires_at = NULL,
                        integrity_status = 'UNKNOWN'
                    WHERE pending_expires_at IS NOT NULL 
                    AND pending_expires_at <= ?
                """, (current_mono,))
                
                conn.commit()
                count = cursor.rowcount
                
                if count > 0:
                    logger.info(f"Cleaned up {count} expired leases")
                
                return count
                
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Error cleaning up expired leases: {e}")
                return 0

    def close(self):
        """Закрытие хранилища"""
        if self._memory_conn:
            self._memory_conn.close()
            self._memory_conn = None
        logger.info("StateStore закрыт")