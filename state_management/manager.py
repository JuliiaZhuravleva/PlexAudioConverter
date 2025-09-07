#!/usr/bin/env python3
"""
State Manager - Главный модуль системы управления состояниями
Единое API для работы со всеми компонентами state management
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import signal
import json

from .store import StateStore
from .planner import StatePlanner
from .machine import AudioStateMachine, create_state_machine
from .config import (
    StateConfig, StateConfigManager, get_config, init_config, 
    get_development_config, get_production_config, setup_logging
)
from .metrics import get_metrics, MetricNames, increment_counter
from .enums import IntegrityStatus, ProcessedStatus

logger = logging.getLogger(__name__)


class StateManager:
    """
    Главный менеджер системы управления состояниями
    Предоставляет единое API для всех операций
    """

    def __init__(self, config_path: Optional[Union[str, Path]] = None, 
                 config_override: Optional[Dict[str, Any]] = None):
        """
        Инициализация менеджера состояний
        
        Args:
            config_path: путь к файлу конфигурации ИЛИ StateConfig для backward compatibility
            config_override: переопределения конфигурации ИЛИ StateStore для backward compatibility
        """
        # Backward compatibility: detect old signature StateManager(config, store)  
        if hasattr(config_path, 'to_dict') and hasattr(config_override, 'upsert_file'):
            # Old style: StateManager(StateConfig, StateStore)
            logger.debug("Using backward compatibility mode: StateManager(StateConfig, StateStore)")
            self.config = config_path  # StateConfig object
            self._test_store = config_override  # StateStore object
            self.config_manager = None
            self._compatibility_mode = True
        else:
            # New style: StateManager(config_path, config_override)
            self._compatibility_mode = False
            
            # Инициализируем конфигурацию
            self.config_manager = init_config(config_path)
            self.config = self.config_manager.load_config()
            
            # Применяем переопределения
            if config_override:
                self.config_manager.update_config(config_override)
                self.config = self.config_manager.get_config()
        
        # Настраиваем логирование
        setup_logging(self.config)
        
        # Создаем основные компоненты
        if self._compatibility_mode:
            # В compatibility mode используем переданный store
            from .machine import AudioStateMachine
            from .planner import StatePlanner
            
            # Создаем planner с тестовым store
            planner = StatePlanner(self._test_store, self.config.to_dict())
            
            # Создаем state machine с тестовыми компонентами  
            self.state_machine = AudioStateMachine(self._test_store, self.config.to_dict())
            # Manually set planner for compatibility
            self.state_machine.planner = planner
        else:
            # Обычный режим
            self.state_machine = create_state_machine(
                self.config.storage_url, 
                self.config.to_dict()
            )
        
        # Инициализируем метрики
        if self.config.metrics_enabled:
            self.metrics = get_metrics()
        else:
            self.metrics = None
        
        self._running = False
        self._main_task = None
        
        logger.info("StateManager инициализирован")
        # Метрики инициализированы и готовы к сбору

    # === Основные операции ===

    async def discover_directory(self, directory: Union[str, Path], 
                               delete_original: bool = False) -> Dict[str, Any]:
        """
        Обнаружение и добавление файлов из директории
        
        Args:
            directory: путь к директории
            delete_original: режим удаления оригиналов
        
        Returns:
            Результат сканирования
        """
        directory_path = Path(directory)
        start_time = datetime.now()
        
        logger.info(f"Начинаем сканирование: {directory_path}")
        
        try:
            discovered_count = await self.state_machine.discover_directory(
                directory_path, delete_original
            )
            
            if self.metrics:
                increment_counter(MetricNames.FILES_DISCOVERED, {'count': str(discovered_count)})
            
            result = {
                'directory': str(directory_path),
                'discovered_files': discovered_count,
                'delete_original': delete_original,
                'scan_time': (datetime.now() - start_time).total_seconds(),
                'status': 'success'
            }
            
            logger.info(f"Сканирование завершено: {discovered_count} файлов")
            
            # Backward compatibility: add expected keys for tests
            result['files_added'] = discovered_count  # Legacy key
            result['files_updated'] = 0  # Legacy key
            
            return result
            
        except Exception as e:
            error_result = {
                'directory': str(directory_path),
                'error': str(e),
                'scan_time': (datetime.now() - start_time).total_seconds(),
                'status': 'error'
            }
            
            logger.error(f"Ошибка сканирования {directory_path}: {e}")
            return error_result

    async def process_file(self, file_path: Union[str, Path], 
                          delete_original: bool = False) -> Dict[str, Any]:
        """
        Обработка конкретного файла
        
        Args:
            file_path: путь к файлу
            delete_original: режим удаления оригиналов
        
        Returns:
            Информация о файле и результат обработки
        """
        path = Path(file_path)
        start_time = datetime.now()
        
        logger.info(f"Обработка файла: {path.name}")
        
        try:
            # Обрабатываем файл
            entry = await self.state_machine.process_file(path, delete_original)
            
            # Получаем актуальный статус
            status = self.state_machine.get_file_status(path)
            
            result = {
                'file_path': str(path),
                'file_id': entry.id,
                'group_id': entry.group_id,
                'is_stereo': entry.is_stereo,
                'integrity_status': entry.integrity_status.value,
                'processed_status': entry.processed_status.value,
                'size_bytes': entry.size_bytes,
                'processing_time': (datetime.now() - start_time).total_seconds(),
                'status': 'processed'
            }
            
            # Добавляем дополнительную информацию если есть
            if entry.integrity_score is not None:
                result['integrity_score'] = entry.integrity_score
            if entry.has_en2 is not None:
                result['has_en2'] = entry.has_en2
            if entry.last_error:
                result['last_error'] = entry.last_error
            
            logger.info(f"Файл обработан: {path.name} -> {entry.processed_status.value}")
            return result
            
        except Exception as e:
            error_result = {
                'file_path': str(path),
                'error': str(e),
                'processing_time': (datetime.now() - start_time).total_seconds(),
                'status': 'error'
            }
            
            logger.error(f"Ошибка обработки {path}: {e}")
            return error_result

    async def process_pending(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Обработка файлов, ожидающих проверки
        
        Args:
            limit: максимальное количество файлов
        
        Returns:
            Результат обработки
        """
        start_time = datetime.now()
        
        try:
            processed_count = await self.state_machine.process_pending_files(limit)
            
            if self.metrics:
                increment_counter(MetricNames.DUE_FILES_PROCESSED, {'count': str(processed_count)})
            
            result = {
                'processed_files': processed_count,
                'processing_time': (datetime.now() - start_time).total_seconds(),
                'status': 'success'
            }
            
            if processed_count > 0:
                logger.info(f"Обработано файлов: {processed_count}")
            
            return result
            
        except Exception as e:
            error_result = {
                'error': str(e),
                'processing_time': (datetime.now() - start_time).total_seconds(),
                'status': 'error'
            }
            
            logger.error(f"Ошибка обработки ожидающих файлов: {e}")
            return error_result

    # === Информационные методы ===

    def get_system_status(self) -> Dict[str, Any]:
        """Получение статуса системы"""
        machine_status = self.state_machine.get_status()
        
        status = {
            'timestamp': datetime.now().isoformat(),
            'running': self._running,
            'config': {
                'storage_url': self.config.storage_url,
                'stable_wait_sec': self.config.stable_wait_sec,
                'batch_size': self.config.batch_size,
                'metrics_enabled': self.config.metrics_enabled
            },
            'store_stats': machine_status['store_stats'],
            'planner_status': machine_status['planner_status']
        }
        
        # Добавляем метрики если включены
        if self.metrics:
            status['metrics'] = self.metrics.get_summary(since_hours=1.0)
        
        return status

    def get_file_info(self, file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Получение информации о файле
        
        Args:
            file_path: путь к файлу
        
        Returns:
            Информация о файле или None если не найден
        """
        return self.state_machine.get_file_status(Path(file_path))

    def get_group_info(self, group_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение информации о группе файлов
        
        Args:
            group_id: идентификатор группы
        
        Returns:
            Информация о группе или None если не найдена
        """
        return self.state_machine.get_group_status(group_id)

    def get_files_by_status(self, integrity_status: Optional[str] = None,
                           processed_status: Optional[str] = None,
                           limit: int = 100) -> Dict[str, Any]:
        """
        Получение файлов по статусу
        
        Args:
            integrity_status: фильтр по статусу целостности
            processed_status: фильтр по статусу обработки
            limit: максимальное количество файлов
        
        Returns:
            Статистика файлов по статусам
        """
        # TODO: Реализовать в StateStore запрос с фильтрами
        # Пока что возвращаем общую статистику
        stats = self.state_machine.store.get_stats()
        return {
            'integrity_stats': stats.get('integrity_status', {}),
            'processed_stats': stats.get('processed_status', {}),
            'total_files': stats.get('total_files', 0)
        }

    # === Операции обслуживания ===

    async def run_maintenance(self) -> Dict[str, Any]:
        """Выполнение операций обслуживания"""
        logger.info("Запуск обслуживания системы")
        
        try:
            result = await self.state_machine.maintenance()
            
            if self.metrics:
                deleted_count = result.get('deleted_entries', 0)
                increment_counter(MetricNames.STATE_ENTRIES_PRUNED, {'count': str(deleted_count)})
            
            logger.info(f"Обслуживание завершено: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка обслуживания: {e}")
            return {'error': str(e), 'status': 'error'}

    def backup_database(self, backup_path: Union[str, Path]) -> bool:
        """
        Создание резервной копии базы данных
        
        Args:
            backup_path: путь для сохранения копии
        
        Returns:
            True если копия создана успешно
        """
        try:
            success = self.state_machine.store.backup_database(backup_path)
            if success:
                logger.info(f"Резервная копия создана: {backup_path}")
            return success
        except Exception as e:
            logger.error(f"Ошибка создания резервной копии: {e}")
            return False

    def export_metrics(self, output_path: Union[str, Path]) -> bool:
        """
        Экспорт метрик в файл
        
        Args:
            output_path: путь для сохранения метрик
        
        Returns:
            True если экспорт выполнен успешно
        """
        if not self.metrics:
            logger.warning("Метрики отключены")
            return False
        
        try:
            self.metrics.export_events(Path(output_path))
            logger.info(f"Метрики экспортированы: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка экспорта метрик: {e}")
            return False

    # === Управление жизненным циклом ===

    async def start_monitoring(self):
        """Запуск мониторинга в фоновом режиме"""
        if self._running:
            logger.warning("Мониторинг уже запущен")
            return
        
        logger.info("Запуск фонового мониторинга")
        self._running = True
        
        # Настройка обработки сигналов
        def signal_handler(signum, frame):
            logger.info(f"Получен сигнал {signum}, останавливаем мониторинг")
            self.stop_monitoring()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Запускаем основной цикл
        self._main_task = asyncio.create_task(self.state_machine.run_monitoring_loop())
        
        try:
            await self._main_task
        except asyncio.CancelledError:
            logger.info("Мониторинг остановлен")
        except Exception as e:
            logger.error(f"Ошибка в мониторинге: {e}")
        finally:
            self._running = False

    def stop_monitoring(self):
        """Остановка мониторинга"""
        if not self._running:
            return
        
        logger.info("Остановка мониторинга")
        self._running = False
        
        self.state_machine.stop()
        
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()

    async def shutdown(self):
        """Корректное завершение работы"""
        logger.info("Завершение работы StateManager")
        
        self.stop_monitoring()
        
        # Финальный экспорт метрик если настроен
        if self.metrics and self.config.metrics_export_path:
            try:
                self.export_metrics(self.config.metrics_export_path)
            except Exception as e:
                logger.error(f"Ошибка финального экспорта метрик: {e}")
        
        logger.info("StateManager завершил работу")

    # === Конфигурация ===

    def reload_config(self) -> Dict[str, Any]:
        """Перезагрузка конфигурации"""
        try:
            old_config = self.config.to_dict()
            self.config = self.config_manager.load_config(reload=True)
            new_config = self.config.to_dict()
            
            # Определяем изменения
            changes = {}
            for key, new_value in new_config.items():
                old_value = old_config.get(key)
                if old_value != new_value:
                    changes[key] = {'old': old_value, 'new': new_value}
            
            if changes:
                logger.info(f"Конфигурация перезагружена: {len(changes)} изменений")
                setup_logging(self.config)
            else:
                logger.info("Конфигурация перезагружена: изменений нет")
            
            return {
                'status': 'success',
                'changes_count': len(changes),
                'changes': changes
            }
            
        except Exception as e:
            logger.error(f"Ошибка перезагрузки конфигурации: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновление конфигурации
        
        Args:
            updates: словарь с обновлениями
        
        Returns:
            Результат обновления
        """
        try:
            self.config_manager.update_config(updates)
            self.config = self.config_manager.get_config()
            
            logger.info(f"Конфигурация обновлена: {len(updates)} параметров")
            
            return {
                'status': 'success',
                'updated_params': list(updates.keys())
            }
            
        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    # === Backward Compatibility Methods for Tests ===
    
    def register_file(self, file_path: Union[str, Path]) -> 'FileEntry':
        """
        Backward compatibility method for direct tests
        Registers a file for tracking (similar to discover but for single file)
        
        Args:
            file_path: path to the file to register
            
        Returns:
            FileEntry object for the registered file
        """
        from .models import FileEntry
        from .enums import IntegrityStatus, ProcessedStatus
        import time
        import os
        
        file_path = Path(file_path)
        
        # Check if file exists
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")
        
        # Get file stats
        stat = file_path.stat()
        
        # Create FileEntry
        entry = FileEntry(
            path=str(file_path.absolute()),
            size_bytes=int(stat.st_size),
            mtime=int(stat.st_mtime),
            integrity_status=IntegrityStatus.UNKNOWN,
            processed_status=ProcessedStatus.NEW,
            first_seen_at=int(time.time()),
            next_check_at=int(time.time()),  # Immediately due
            is_stereo='.stereo.' in file_path.name.lower()
        )
        
        # Store in database
        stored_entry = self.state_machine.store.upsert_file(entry)
        logger.debug(f"Registered file: {file_path} (ID: {stored_entry.id})")
        
        return stored_entry

    @property
    def store(self):
        """Backward compatibility property to access store"""
        if self._compatibility_mode and hasattr(self, '_test_store'):
            return self._test_store
        return self.state_machine.store
        
    @store.setter 
    def store(self, value):
        """Backward compatibility setter to replace store (for tests)"""
        if self._compatibility_mode:
            self._test_store = value
            # Update state machine components if they exist
            if hasattr(self, 'state_machine') and self.state_machine:
                self.state_machine.store = value
                if hasattr(self.state_machine, 'planner') and self.state_machine.planner:
                    self.state_machine.planner.store = value
        else:
            if hasattr(self, 'state_machine') and self.state_machine:
                self.state_machine.store = value
                if hasattr(self.state_machine, 'planner') and self.state_machine.planner:
                    self.state_machine.planner.store = value


# === Фабричные функции ===

def create_state_manager(config_path: Optional[Union[str, Path]] = None,
                        config_override: Optional[Dict[str, Any]] = None,
                        environment: str = 'production') -> StateManager:
    """
    Создание менеджера состояний
    
    Args:
        config_path: путь к конфигурации
        config_override: переопределения конфигурации
        environment: окружение (development, production)
    
    Returns:
        Настроенный StateManager
    """
    # Выбираем базовую конфигурацию
    if environment == 'development':
        base_config = get_development_config().to_dict()
    else:
        base_config = get_production_config().to_dict()
    
    # Объединяем с переопределениями
    if config_override:
        base_config.update(config_override)
    
    manager = StateManager(config_path, base_config)
    
    logger.info(f"StateManager создан для окружения: {environment}")
    return manager


async def run_state_manager_cli():
    """CLI для запуска менеджера состояний"""
    import argparse
    
    parser = argparse.ArgumentParser(description='State Manager CLI')
    parser.add_argument('--config', type=str, help='Путь к конфигурации')
    parser.add_argument('--env', choices=['development', 'production'], 
                       default='production', help='Окружение')
    parser.add_argument('--scan', type=str, help='Сканировать директорию')
    parser.add_argument('--delete-original', action='store_true', 
                       help='Удалять оригиналы при конвертации')
    parser.add_argument('--monitor', action='store_true', 
                       help='Запустить фоновый мониторинг')
    parser.add_argument('--status', action='store_true', 
                       help='Показать статус системы')
    parser.add_argument('--maintenance', action='store_true', 
                       help='Выполнить обслуживание')
    
    args = parser.parse_args()
    
    # Создаем менеджер
    manager = create_state_manager(args.config, environment=args.env)
    
    try:
        if args.scan:
            result = await manager.discover_directory(args.scan, args.delete_original)
            print(json.dumps(result, indent=2))
        
        elif args.status:
            status = manager.get_system_status()
            print(json.dumps(status, indent=2, default=str))
        
        elif args.maintenance:
            result = await manager.run_maintenance()
            print(json.dumps(result, indent=2))
        
        elif args.monitor:
            print("Запуск мониторинга (Ctrl+C для остановки)...")
            await manager.start_monitoring()
        
        else:
            parser.print_help()
    
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(run_state_manager_cli())