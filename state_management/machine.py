#!/usr/bin/env python3
"""
State Machine - Логика переходов состояний и обработчики событий
Координация между компонентами и выполнение бизнес-логики
"""

import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Awaitable
import json
import subprocess

from .store import StateStore
from .planner import StatePlanner, PlannerAction, PlannerTask
from .models import FileEntry, GroupEntry
from .enums import IntegrityStatus, ProcessedStatus, IntegrityMode
from .integrity_adapter import get_integrity_adapter
from .metrics import get_metrics, MetricNames, MetricTimer

logger = logging.getLogger(__name__)


class StateMachineError(Exception):
    """Ошибки конечного автомата"""
    pass


class AudioStateMachine:
    """Конечный автомат для управления жизненным циклом аудиофайлов"""

    def __init__(self, state_store: StateStore, config: Dict[str, Any] = None):
        """
        Инициализация конечного автомата
        
        Args:
            state_store: хранилище состояний
            config: конфигурация
        """
        self.store = state_store
        self.config = {
            'ffprobe_path': 'ffprobe',
            'stable_wait_sec': 30,
            'integrity_quick_mode': True,
            'integrity_timeout_sec': 300,
            **(config or {})
        }
        
        # Создаем планировщик
        self.planner = StatePlanner(state_store, self.config)
        
        # Создаем адаптер для проверки целостности
        self.integrity_adapter = get_integrity_adapter(
            ffprobe_path=self.config.get('ffprobe_path', 'ffprobe'),
            ffmpeg_path=self.config.get('ffmpeg_path', 'ffmpeg')
        )
        
        # Регистрируем обработчики
        self._register_handlers()
        
        logger.info("AudioStateMachine инициализирован")

    def _register_handlers(self):
        """Регистрация обработчиков действий планировщика"""
        self.planner.register_handler(
            PlannerAction.CHECK_INTEGRITY, 
            self._handle_integrity_check
        )
        self.planner.register_handler(
            PlannerAction.PROCESS_AUDIO, 
            self._handle_audio_analysis
        )
        self.planner.register_handler(
            PlannerAction.CONVERT_AUDIO, 
            self._handle_audio_conversion
        )

    async def _handle_integrity_check(self, task: PlannerTask) -> bool:
        """Обработка проверки целостности файла"""
        entry = task.file_entry
        if not entry:
            return False
        
        file_path = Path(entry.path)
        metrics = get_metrics()
        
        with MetricTimer(MetricNames.INTEGRITY_CHECK):
            try:
                logger.debug(f"Проверка целостности: {file_path.name}")
                
                # Устанавливаем статус PENDING
                entry.update_integrity_status(IntegrityStatus.PENDING)
                
                # Планируем timeout
                timeout_delay = self.config['integrity_timeout_sec']
                entry.schedule_next_check(timeout_delay)
                self.store.upsert_file(entry)
                
                # Выполняем проверку
                mode = IntegrityMode.QUICK if self.config['integrity_quick_mode'] else IntegrityMode.FULL
                
                # Используем адаптер для проверки целостности
                status, score = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    self.integrity_adapter.check_video_integrity,
                    str(file_path),
                    mode
                )
                
                # Обрабатываем результат
                if status == IntegrityStatus.COMPLETE:
                    metrics.increment(MetricNames.INTEGRITY_PASS)
                    entry.update_integrity_status(
                        IntegrityStatus.COMPLETE,
                        score=score,
                        mode=mode
                    )
                    
                    # Планируем следующий шаг (анализ аудио)
                    entry.next_check_at = int(datetime.now().timestamp())
                    
                    logger.info(f"Целостность подтверждена: {file_path.name} (score: {score:.2f})" if score else f"Целостность подтверждена: {file_path.name}")
                    
                else:
                    metrics.increment(MetricNames.INTEGRITY_FAIL)
                    error_msg = f'Статус целостности: {status.value}'
                    
                    entry.update_integrity_status(status, error=error_msg)
                    
                    # Применяем backoff
                    await self.planner.apply_backoff(entry)
                    
                    logger.warning(f"Проблемы с целостностью: {file_path.name} - {error_msg}")
                
                self.store.upsert_file(entry)
                return True
                
            except Exception as e:
                metrics.increment(MetricNames.INTEGRITY_ERROR)
                logger.error(f"Ошибка проверки целостности {file_path}: {e}")
                
                # Устанавливаем статус ERROR
                entry.update_integrity_status(IntegrityStatus.ERROR, error=str(e))
                await self.planner.apply_backoff(entry)
                self.store.upsert_file(entry)
                
                return False

    async def _handle_audio_analysis(self, task: PlannerTask) -> bool:
        """Обработка анализа аудиодорожек"""
        entry = task.file_entry
        if not entry:
            return False
        
        file_path = Path(entry.path)
        
        try:
            logger.debug(f"Анализ аудио: {file_path.name}")
            
            # Получаем информацию об аудиодорожках
            audio_info = await self._get_audio_info(file_path)
            
            if audio_info is None:
                entry.update_processed_status(
                    ProcessedStatus.CONVERT_FAILED,
                    error="Не удалось получить информацию об аудио"
                )
                self.store.upsert_file(entry)
                return False
            
            # Проверяем наличие английской 2.0 дорожки
            has_en2 = self._has_english_stereo(audio_info)
            
            if has_en2:
                # Файл уже имеет нужную дорожку
                entry.update_processed_status(
                    ProcessedStatus.SKIPPED_HAS_EN2,
                    has_en2=True
                )
                
                # Устанавливаем next_check_at в далекое будущее (не нужно больше проверять)
                entry.next_check_at = int(datetime.now().timestamp()) + 365 * 24 * 3600
                
                logger.info(f"Уже имеет EN 2.0 дорожку: {file_path.name}")
            else:
                # Нужна конвертация
                entry.has_en2 = False
                
                # Проверяем, есть ли многоканальная английская дорожка
                has_surround = self._has_english_surround(audio_info)
                
                if has_surround:
                    # Готов к конвертации
                    entry.next_check_at = int(datetime.now().timestamp())
                    logger.info(f"Готов к конвертации: {file_path.name}")
                else:
                    # Нет подходящих дорожек для конвертации
                    entry.update_processed_status(
                        ProcessedStatus.IGNORED,
                        error="Нет подходящих английских многоканальных дорожек"
                    )
                    entry.next_check_at = int(datetime.now().timestamp()) + 365 * 24 * 3600
                    logger.info(f"Нет подходящих дорожек: {file_path.name}")
            
            self.store.upsert_file(entry)
            return True
            
        except Exception as e:
            logger.error(f"Ошибка анализа аудио {file_path}: {e}")
            
            entry.update_processed_status(
                ProcessedStatus.CONVERT_FAILED,
                error=str(e)
            )
            await self.planner.apply_backoff(entry)
            self.store.upsert_file(entry)
            
            return False

    async def _handle_audio_conversion(self, task: PlannerTask) -> bool:
        """Обработка конвертации аудио (заглушка для будущей реализации)"""
        entry = task.file_entry
        if not entry:
            return False
        
        logger.info(f"Конвертация аудио запланирована: {entry.path}")
        
        # Пока что только помечаем как готовый к конвертации
        # В следующих итерациях здесь будет реальная конвертация
        
        return True

    async def _get_audio_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Получение информации об аудиодорожках с помощью ffprobe"""
        try:
            cmd = [
                self.config['ffprobe_path'],
                '-v', 'error',
                '-print_format', 'json',
                '-show_streams',
                '-select_streams', 'a',
                str(file_path)
            ]
            
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data
            else:
                logger.error(f"ffprobe failed: {result.stderr}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка ffprobe для {file_path}: {e}")
            return None

    def _has_english_stereo(self, audio_info: Dict[str, Any]) -> bool:
        """Проверка наличия английской стерео дорожки"""
        streams = audio_info.get('streams', [])
        
        for stream in streams:
            channels = stream.get('channels', 0)
            if channels != 2:
                continue
            
            # Проверяем язык
            tags = stream.get('tags', {})
            language = tags.get('language', 'und').lower()
            title = tags.get('title', '').lower()
            
            is_english = (
                language in ['eng', 'en', 'english'] or
                'eng' in title or 'english' in title
            )
            
            if is_english:
                return True
        
        return False

    def _has_english_surround(self, audio_info: Dict[str, Any]) -> bool:
        """Проверка наличия английской многоканальной дорожки"""
        streams = audio_info.get('streams', [])
        
        for stream in streams:
            channels = stream.get('channels', 0)
            if channels <= 2:
                continue
            
            # Проверяем язык
            tags = stream.get('tags', {})
            language = tags.get('language', 'und').lower()
            title = tags.get('title', '').lower()
            
            is_english = (
                language in ['eng', 'en', 'english'] or
                'eng' in title or 'english' in title
            )
            
            if is_english:
                return True
        
        return False

    # === Публичные методы ===

    async def discover_directory(self, directory: Path, delete_original: bool = False) -> int:
        """
        Обнаружение файлов в директории
        
        Args:
            directory: директория для сканирования
            delete_original: режим удаления оригиналов
        
        Returns:
            Количество обнаруженных файлов
        """
        logger.info(f"Сканирование директории: {directory}")
        count = await self.planner.scan_directory(directory, delete_original)
        return count

    async def process_file(self, file_path: Path, delete_original: bool = False) -> FileEntry:
        """
        Обработка конкретного файла
        
        Args:
            file_path: путь к файлу
            delete_original: режим удаления оригиналов
        
        Returns:
            FileEntry с актуальным состоянием
        """
        entry = await self.planner.discover_file(file_path, delete_original)
        
        # Обрабатываем файл немедленно если он готов
        if entry.is_due_for_check():
            await self.planner.process_due_files(limit=1)
            # Получаем обновленное состояние
            entry = self.store.get_file(file_path) or entry
        
        return entry

    async def process_pending_files(self, limit: int = None) -> int:
        """
        Обработка файлов, ожидающих проверки
        
        Args:
            limit: максимальное количество файлов
        
        Returns:
            Количество обработанных файлов
        """
        return await self.planner.process_due_files(limit)

    async def run_monitoring_loop(self):
        """Запуск основного цикла мониторинга"""
        await self.planner.monitoring_loop()

    def stop(self):
        """Остановка конечного автомата"""
        logger.info("Остановка AudioStateMachine")
        self.planner.stop()

    def get_status(self) -> Dict[str, Any]:
        """Получение статуса системы"""
        return {
            'planner_status': self.planner.get_status(),
            'store_stats': self.store.get_stats(),
            'config': self.config
        }

    def get_file_status(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Получение статуса конкретного файла"""
        entry = self.store.get_file(file_path)
        if entry:
            return {
                'path': entry.path,
                'group_id': entry.group_id,
                'is_stereo': entry.is_stereo,
                'size_bytes': entry.size_bytes,
                'first_seen_at': datetime.fromtimestamp(entry.first_seen_at).isoformat(),
                'stable_since': datetime.fromtimestamp(entry.stable_since).isoformat() if entry.stable_since else None,
                'next_check_at': datetime.fromtimestamp(entry.next_check_at).isoformat(),
                'integrity_status': entry.integrity_status.value,
                'integrity_score': entry.integrity_score,
                'integrity_fail_count': entry.integrity_fail_count,
                'processed_status': entry.processed_status.value,
                'has_en2': entry.has_en2,
                'last_error': entry.last_error,
                'updated_at': datetime.fromtimestamp(entry.updated_at).isoformat()
            }
        return None

    def get_group_status(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Получение статуса группы файлов"""
        group = self.store.get_group(group_id)
        files = self.store.get_files_by_group(group_id)
        
        if group:
            return {
                'group_id': group.group_id,
                'delete_original': group.delete_original,
                'original_present': group.original_present,
                'stereo_present': group.stereo_present,
                'pair_status': group.pair_status.value,
                'processed_status': group.processed_status.value,
                'first_seen_at': datetime.fromtimestamp(group.first_seen_at).isoformat(),
                'updated_at': datetime.fromtimestamp(group.updated_at).isoformat(),
                'files_count': len(files),
                'files': [{'path': f.path, 'is_stereo': f.is_stereo, 'processed_status': f.processed_status.value} for f in files]
            }
        return None

    async def maintenance(self) -> Dict[str, Any]:
        """Выполнение обслуживания системы"""
        return await self.planner.run_maintenance()


# === Фабричная функция ===

def create_state_machine(db_path: str = "state.db", config: Dict[str, Any] = None) -> AudioStateMachine:
    """
    Создание экземпляра конечного автомата
    
    Args:
        db_path: путь к базе данных
        config: конфигурация
    
    Returns:
        Настроенный AudioStateMachine
    """
    store = StateStore(db_path)
    machine = AudioStateMachine(store, config)
    
    logger.info(f"AudioStateMachine создан (db: {db_path})")
    return machine