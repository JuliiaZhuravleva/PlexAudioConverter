#!/usr/bin/env python3
"""
State Store - Хранилище состояний на базе SQLite
Устойчивое, дешёвое по ресурсам state-хранилище с транзакциями и индексацией
"""

import sqlite3
import json
import logging
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
            updated_at INTEGER NOT NULL
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
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        
        # Создаем директорию если нужно
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Инициализируем БД
        self._init_database()
        
        logger.info(f"StateStore инициализирован: {self.db_path}")

    def _init_database(self):
        """Инициализация структуры БД"""
        with self._get_connection() as conn:
            # Создаем таблицы
            conn.execute(self.SCHEMA_FILES)
            conn.execute(self.SCHEMA_GROUPS)
            
            # Создаем индексы
            for index_sql in self.INDEXES:
                conn.execute(index_sql)
            
            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Получение подключения к БД с блокировкой"""
        with self._lock:
            conn = sqlite3.connect(
                self.db_path,
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
            entry.updated_at
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

    def upsert_file(self, entry: FileEntry) -> FileEntry:
        """
        Обновление или создание файла
        Возвращает обновленный FileEntry с заполненным ID
        """
        with self._get_connection() as conn:
            try:
                if entry.id is None:
                    # Создание нового файла
                    cursor = conn.execute("""
                        INSERT INTO files (
                            path, group_id, is_stereo, size_bytes, mtime,
                            first_seen_at, stable_since, next_check_at,
                            integrity_status, integrity_score, integrity_mode_used,
                            integrity_fail_count, processed_status, has_en2,
                            last_error, extra, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, self._file_entry_to_values(entry))
                    
                    entry.id = cursor.lastrowid
                else:
                    # Обновление существующего файла
                    conn.execute("""
                        UPDATE files SET
                            path = ?, group_id = ?, is_stereo = ?, size_bytes = ?, mtime = ?,
                            first_seen_at = ?, stable_since = ?, next_check_at = ?,
                            integrity_status = ?, integrity_score = ?, integrity_mode_used = ?,
                            integrity_fail_count = ?, processed_status = ?, has_en2 = ?,
                            last_error = ?, extra = ?, updated_at = ?
                        WHERE id = ?
                    """, self._file_entry_to_values(entry) + (entry.id,))
                
                conn.commit()
                logger.debug(f"Файл сохранён: {entry.path} (ID: {entry.id})")
                return entry
                
            except sqlite3.IntegrityError as e:
                conn.rollback()
                raise StateStoreError(f"Ошибка сохранения файла {entry.path}: {e}")

    def get_due_files(self, current_time: Optional[int] = None, limit: int = 100) -> List[FileEntry]:
        """
        Получение файлов, готовых к проверке
        
        Args:
            current_time: текущее время (по умолчанию - сейчас)
            limit: максимальное количество файлов
        
        Returns:
            Список FileEntry, отсортированный по next_check_at
        """
        if current_time is None:
            current_time = int(datetime.now().timestamp())
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM files 
                WHERE next_check_at <= ?
                ORDER BY next_check_at ASC
                LIMIT ?
            """, (current_time, limit))
            
            files = []
            for row in cursor.fetchall():
                files.append(self._row_to_file_entry(row))
            
            return files

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
            import shutil
            backup_path = Path(backup_path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(self.db_path, backup_path)
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

    def close(self):
        """Закрытие хранилища"""
        logger.info("StateStore закрыт")