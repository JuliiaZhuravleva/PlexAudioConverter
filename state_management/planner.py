#!/usr/bin/env python3
"""
State Planner - Планировщик задач для управления состояниями
Вытаскивает «готовые к действию» записи и координирует их обработку
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass
import time
from enum import Enum

from .store import StateStore
from .models import FileEntry, GroupEntry, create_file_entry_from_path, normalize_group_id
from .enums import IntegrityStatus, ProcessedStatus, PairStatus, IntegrityMode
from .metrics import get_metrics, MetricNames

logger = logging.getLogger(__name__)


class PlannerAction(Enum):
    """Типы действий планировщика"""
    DISCOVER_FILE = "DISCOVER_FILE"           # обнаружение нового файла
    CHECK_SIZE_STABILITY = "CHECK_SIZE_STABILITY"  # проверка стабильности размера
    CHECK_INTEGRITY = "CHECK_INTEGRITY"       # проверка целостности
    PROCESS_AUDIO = "PROCESS_AUDIO"          # анализ аудио (ffprobe)
    CONVERT_AUDIO = "CONVERT_AUDIO"          # конвертация аудио
    UPDATE_GROUP = "UPDATE_GROUP"            # обновление группы
    CLEANUP_MISSING = "CLEANUP_MISSING"      # очистка отсутствующих файлов


@dataclass
class PlannerTask:
    """Задача для выполнения планировщиком"""
    action: PlannerAction
    file_entry: Optional[FileEntry] = None
    group_id: Optional[str] = None
    file_path: Optional[str] = None
    priority: int = 0  # чем меньше, тем выше приоритет
    scheduled_at: int = 0  # время планирования
    
    def __post_init__(self):
        if self.scheduled_at == 0:
            self.scheduled_at = int(datetime.now().timestamp())


class StatePlanner:
    """Планировщик для управления жизненным циклом файлов"""

    def __init__(self, state_store: StateStore, config: Dict[str, Any] = None):
        """
        Инициализация планировщика
        
        Args:
            state_store: хранилище состояний
            config: конфигурация планировщика
        """
        self.store = state_store
        self.config = {
            'stable_wait_sec': 30,
            'backoff_step_sec': 30,
            'backoff_max_sec': 600,
            'batch_size': 50,
            'loop_interval_sec': 5,
            'integrity_timeout_sec': 300,
            **(config or {})
        }
        
        # Обработчики действий
        self._action_handlers: Dict[PlannerAction, Callable] = {}
        self._running = False
        self._task_queue = asyncio.Queue()
        self._last_maintenance_at = 0
        
        logger.info(f"StatePlanner инициализирован (stable_wait={self.config['stable_wait_sec']}s)")

    def register_handler(self, action: PlannerAction, 
                        handler: Callable[[PlannerTask], Awaitable[bool]]):
        """
        Регистрация обработчика действия
        
        Args:
            action: тип действия
            handler: асинхронная функция-обработчик, возвращает True при успехе
        """
        self._action_handlers[action] = handler
        logger.debug(f"Зарегистрирован обработчик для {action.value}")

    async def discover_file(self, file_path: Path, delete_original: bool = False) -> FileEntry:
        """
        Обнаружение нового файла и добавление в систему
        
        Args:
            file_path: путь к файлу
            delete_original: режим удаления оригиналов
        
        Returns:
            Созданный или обновленный FileEntry
        """
        try:
            # Проверяем, существует ли файл в хранилище
            existing = self.store.get_file(file_path)
            
            if existing is None:
                # Создаем новую запись
                entry = create_file_entry_from_path(file_path, delete_original)
                entry.next_check_at = int(datetime.now().timestamp())  # проверить сразу
                entry = self.store.upsert_file(entry)
                
                logger.info(f"Обнаружен новый файл: {file_path.name} (ID: {entry.id})")
            else:
                # Обновляем существующую запись
                stat = file_path.stat()
                entry = existing
                changed = entry.update_file_stats(
                    stat.st_size, 
                    int(stat.st_mtime),
                    self.config['stable_wait_sec']
                )
                
                if changed:
                    entry = self.store.upsert_file(entry)
                    logger.debug(f"Обновлена статистика файла: {file_path.name}")
            
            # Обновляем группу
            await self.update_group_presence(entry.group_id, delete_original)
            
            return entry
            
        except Exception as e:
            logger.error(f"Ошибка обнаружения файла {file_path}: {e}")
            raise

    async def update_group_presence(self, group_id: str, delete_original: bool = False) -> GroupEntry:
        """Обновление информации о присутствии файлов в группе"""
        try:
            group = self.store.update_group_presence(group_id, delete_original)
            logger.debug(f"Обновлена группа: {group_id} (original: {group.original_present}, stereo: {group.stereo_present})")
            return group
        except Exception as e:
            logger.error(f"Ошибка обновления группы {group_id}: {e}")
            raise

    async def process_due_files(self, limit: int = None) -> int:
        """
        Обработка файлов, готовых к проверке
        
        Args:
            limit: максимальное количество файлов для обработки
        
        Returns:
            Количество обработанных файлов
        """
        if limit is None:
            limit = self.config['batch_size']
        
        current_time = int(datetime.now().timestamp())
        due_files = self.store.get_due_files(current_time, limit)
        
        if not due_files:
            return 0
        
        logger.debug(f"Обрабатываем {len(due_files)} файлов, готовых к проверке")
        processed_count = 0
        
        for file_entry in due_files:
            try:
                action = await self._determine_next_action(file_entry)
                if action:
                    task = PlannerTask(action=action, file_entry=file_entry)
                    success = await self._execute_task(task)
                    if success:
                        processed_count += 1
                    
            except Exception as e:
                logger.error(f"Ошибка обработки файла {file_entry.path}: {e}")
                # Планируем повторную проверку через backoff
                await self.apply_backoff(file_entry)
        
        if processed_count > 0:
            logger.info(f"Обработано файлов: {processed_count}/{len(due_files)}")
        
        return processed_count

    async def _determine_next_action(self, entry: FileEntry) -> Optional[PlannerAction]:
        """Определение следующего действия для файла"""
        file_path = Path(entry.path)
        current_time = int(datetime.now().timestamp())
        
        # Проверяем существование файла
        if not file_path.exists():
            logger.debug(f"Файл не существует, планируем очистку: {entry.path}")
            return PlannerAction.CLEANUP_MISSING
        
        # Проверяем изменения размера/времени
        stat = file_path.stat()
        if entry.size_bytes != stat.st_size or entry.mtime != int(stat.st_mtime):
            logger.debug(f"Файл изменился, обновляем статистику: {file_path.name}")
            return PlannerAction.CHECK_SIZE_STABILITY
        
        # Проверяем стабильность
        if entry.stable_since is None:
            if current_time - entry.mtime >= 1:  # файл не менялся минимум 1 секунду
                logger.debug(f"Отмечаем файл как стабильный: {file_path.name}")
                return PlannerAction.CHECK_SIZE_STABILITY
            else:
                # Планируем проверку через секунду
                entry.next_check_at = current_time + 1
                self.store.upsert_file(entry)
                return None
        
        # Проверяем готовность к integrity-проверке
        if not entry.is_stable(self.config['stable_wait_sec']):
            defer_time = entry.stable_since + self.config['stable_wait_sec']
            entry.next_check_at = defer_time
            self.store.upsert_file(entry)
            logger.debug(f"Файл еще не готов к проверке целостности: {file_path.name}")
            return None
        
        # Проверка целостности
        if entry.integrity_status in {IntegrityStatus.UNKNOWN, IntegrityStatus.INCOMPLETE, IntegrityStatus.ERROR}:
            logger.debug(f"Планируем проверку целостности: {file_path.name}")
            return PlannerAction.CHECK_INTEGRITY
        
        # Анализ аудио после успешной проверки целостности
        if (entry.integrity_status == IntegrityStatus.COMPLETE and 
            entry.processed_status == ProcessedStatus.NEW and
            entry.has_en2 is None):
            logger.debug(f"Планируем анализ аудио: {file_path.name}")
            return PlannerAction.PROCESS_AUDIO
        
        # Обновление группы после обработки
        if entry.processed_status in {ProcessedStatus.SKIPPED_HAS_EN2, ProcessedStatus.CONVERTED}:
            logger.debug(f"Обновляем группу: {file_path.name}")
            return PlannerAction.UPDATE_GROUP
        
        # Нет действий
        return None

    async def _execute_task(self, task: PlannerTask) -> bool:
        """Выполнение задачи"""
        handler = self._action_handlers.get(task.action)
        if handler:
            try:
                return await handler(task)
            except Exception as e:
                logger.error(f"Ошибка выполнения {task.action.value}: {e}")
                return False
        else:
            # Встроенные обработчики
            return await self._execute_builtin_task(task)

    async def _execute_builtin_task(self, task: PlannerTask) -> bool:
        """Выполнение встроенных задач"""
        try:
            if task.action == PlannerAction.CHECK_SIZE_STABILITY:
                return await self._handle_size_stability(task.file_entry)
            
            elif task.action == PlannerAction.UPDATE_GROUP:
                if task.file_entry:
                    await self.update_group_presence(task.file_entry.group_id)
                elif task.group_id:
                    await self.update_group_presence(task.group_id)
                return True
            
            elif task.action == PlannerAction.CLEANUP_MISSING:
                return await self._handle_cleanup_missing(task.file_entry)
            
            else:
                logger.warning(f"Нет обработчика для {task.action.value}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка встроенного обработчика {task.action.value}: {e}")
            return False

    async def _handle_size_stability(self, entry: FileEntry) -> bool:
        """Обработка проверки стабильности размера"""
        file_path = Path(entry.path)
        
        if not file_path.exists():
            return False
        
        stat = file_path.stat()
        current_time = int(datetime.now().timestamp())
        
        changed = entry.update_file_stats(
            stat.st_size,
            int(stat.st_mtime),
            self.config['stable_wait_sec']
        )
        
        if changed or entry.stable_since is not None:
            self.store.upsert_file(entry)
            
        return True

    async def _handle_cleanup_missing(self, entry: FileEntry) -> bool:
        """Обработка очистки отсутствующих файлов"""
        logger.info(f"Удаляем отсутствующий файл из хранилища: {entry.path}")
        
        # Удаляем файл
        self.store.delete_file(entry.path)
        
        # Обновляем группу
        await self.update_group_presence(entry.group_id)
        
        return True

    async def apply_backoff(self, entry: FileEntry):
        """Применение backoff для повторной проверки"""
        metrics = get_metrics()
        metrics.increment(MetricNames.BACKOFF_APPLIED)
        
        # Линейный backoff: step, 2*step, 3*step, ..., max
        backoff_multiplier = min(max(1, entry.integrity_fail_count), 
                               self.config['backoff_max_sec'] // self.config['backoff_step_sec'])
        delay = min(
            self.config['backoff_step_sec'] * backoff_multiplier,
            self.config['backoff_max_sec']
        )
        
        entry.schedule_next_check(delay)
        self.store.upsert_file(entry)
        
        logger.debug(f"Backoff {delay}s для {entry.path} (попытка #{entry.integrity_fail_count})")

    async def scan_directory(self, directory: Path, delete_original: bool = False, 
                           max_depth: Optional[int] = None) -> int:
        """
        Сканирование директории и добавление новых файлов
        
        Args:
            directory: директория для сканирования
            delete_original: режим удаления оригиналов
            max_depth: максимальная глубина рекурсии
        
        Returns:
            Количество обнаруженных файлов
        """
        if max_depth is None:
            max_depth = self.config.get('max_scan_depth', 2)
        
        video_extensions = set(self.config.get('video_extensions', ['.mp4', '.mkv', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.webm']))
        discovered_count = 0
        discovered_files = []
        
        def scan_recursive(path: Path, current_depth: int = 0) -> int:
            if current_depth > max_depth:
                return 0
            
            count = 0
            try:
                for item in path.iterdir():
                    if item.is_file() and item.suffix.lower() in video_extensions:
                        # Собираем файлы для пакетной обработки
                        discovered_files.append(item)
                        count += 1
                    elif item.is_dir() and current_depth < max_depth:
                        count += scan_recursive(item, current_depth + 1)
            except PermissionError:
                logger.warning(f"Нет доступа к {path}")
            
            return count
        
        discovered_count = scan_recursive(directory)
        
        # Пакетная обработка файлов с семафором для ограничения конкурентности
        if discovered_files:
            max_concurrent = self.config.get('max_concurrent_discovery', 10)
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def discover_with_semaphore(file_path: Path):
                async with semaphore:
                    await self.discover_file(file_path, delete_original)
            
            # Обрабатываем файлы пакетами
            tasks = [discover_with_semaphore(file_path) for file_path in discovered_files]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        if discovered_count > 0:
            logger.info(f"Обнаружено и обработано файлов в {directory}: {discovered_count}")
        
        return discovered_count

    async def run_maintenance(self) -> Dict[str, Any]:
        """Выполнение задач обслуживания"""
        logger.info("Запуск обслуживания StateStore...")
        
        stats = {}
        
        # GC старых записей
        deleted_count = self.store.cleanup_old_entries(
            max_entries=self.config.get('max_state_entries', 5000),
            keep_processed_days=self.config.get('keep_processed_days', 30)
        )
        stats['deleted_entries'] = deleted_count
        
        # Получаем статистику
        store_stats = self.store.get_stats()
        stats.update(store_stats)
        
        # Оптимизация БД если нужно
        if deleted_count > 100:
            self.store.vacuum_database()
            stats['vacuum_performed'] = True
        
        logger.info(f"Обслуживание завершено: {stats}")
        return stats

    async def monitoring_loop(self):
        """Основной цикл мониторинга"""
        logger.info("Запуск цикла мониторинга StatePlanner")
        self._running = True
        
        try:
            while self._running:
                start_time = time.time()
                
                # Обрабатываем готовые файлы
                processed = await self.process_due_files()
                
                # Периодическое обслуживание (каждые 10 минут)
                maintenance_interval = 600  # 10 минут
                if (start_time - self._last_maintenance_at) >= maintenance_interval:
                    await self.run_maintenance()
                    self._last_maintenance_at = start_time
                
                # Пауза между итерациями
                elapsed = time.time() - start_time
                sleep_time = max(0, self.config['loop_interval_sec'] - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                
        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")
        finally:
            self._running = False
            logger.info("Цикл мониторинга StatePlanner завершен")

    def stop(self):
        """Остановка планировщика"""
        logger.info("Остановка StatePlanner...")
        self._running = False

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса планировщика"""
        return {
            'running': self._running,
            'config': self.config,
            'registered_handlers': list(self._action_handlers.keys()),
            'store_stats': self.store.get_stats()
        }