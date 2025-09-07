#!/usr/bin/env python3
"""
Discovery Adapter - Тонкая прослойка для платформенных edge-тестов

Предоставляет API старого scan_directory для тестов T-501...T-504
без повторного введения legacy кода в основную систему
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from .store import StateStore
from .planner import StatePlanner

logger = logging.getLogger(__name__)


class DiscoveryAdapter:
    """
    Адаптер для подключения платформенных edge-тестов к новой state API
    
    Минималистичная обертка (50-100 LOC) исключительно для fix тестов,
    без re-entanglement с legacy кодом
    """

    def __init__(self, state_store: StateStore, state_planner: StatePlanner):
        """
        Инициализация адаптера
        
        Args:
            state_store: хранилище состояний
            state_planner: планировщик задач
        """
        self.store = state_store
        self.planner = state_planner
        logger.debug("DiscoveryAdapter инициализирован")

    def discover_path(self, path: Union[str, Path]) -> Dict[str, Any]:
        """
        Обнаружение одного файла или директории
        
        Args:
            path: путь к файлу или директории
        
        Returns:
            Результат обнаружения с количеством найденных файлов
        """
        path_obj = Path(path)
        
        if path_obj.is_file():
            return asyncio.run(self._discover_file(path_obj))
        elif path_obj.is_dir():
            return self.discover_directory(path_obj)
        else:
            logger.warning(f"Путь не существует или недоступен: {path}")
            return {'files_added': 0, 'files_updated': 0, 'error': 'Path not found'}

    def discover_directory(self, directory: Union[str, Path], delete_original: bool = False) -> Dict[str, Any]:
        """
        Обнаружение файлов в директории (sync обертка над async scan_directory)
        
        Args:
            directory: директория для сканирования
            delete_original: режим удаления оригиналов
        
        Returns:
            Результат сканирования
        """
        directory_path = Path(directory)
        
        if not directory_path.exists() or not directory_path.is_dir():
            logger.warning(f"Директория не существует: {directory}")
            return {'files_added': 0, 'files_updated': 0, 'error': 'Directory not found'}
        
        try:
            # Вызываем async метод через event loop
            new_files_count = asyncio.run(
                self.planner.scan_directory(directory_path, delete_original)
            )
            
            return {
                'files_added': new_files_count,
                'files_updated': 0,  # Planner не различает добавленные vs обновленные
                'directory': str(directory_path),
                'delete_original': delete_original
            }
        except Exception as e:
            logger.error(f"Ошибка сканирования директории {directory}: {e}")
            return {'files_added': 0, 'files_updated': 0, 'error': str(e)}

    def refresh_stats(self, directory: Union[str, Path]) -> Dict[str, Any]:
        """
        Обновление статистики файлов в директории
        
        Args:
            directory: директория для обновления статистики
        
        Returns:
            Статистика обновления
        """
        directory_path = Path(directory)
        stats = {'updated_files': 0, 'quarantined_files': 0, 'total_files': 0}
        
        try:
            # Получаем все файлы из директории в store
            all_files = self.store.get_all_files()
            updated_count = 0
            
            for file_entry in all_files:
                file_path = Path(file_entry.path)
                
                # Фильтруем только файлы из указанной директории
                if not file_path.is_relative_to(directory_path):
                    continue
                
                stats['total_files'] += 1
                
                # Проверяем карантин
                if file_entry.is_quarantined():
                    stats['quarantined_files'] += 1
                
                # Обновляем статистику файла если он существует
                if file_path.exists():
                    file_stat = file_path.stat()
                    old_size = file_entry.size_bytes
                    old_mtime = file_entry.mtime
                    
                    if file_entry.update_file_stats(
                        int(file_stat.st_size), 
                        int(file_stat.st_mtime)
                    ):
                        self.store.upsert_file(file_entry)
                        updated_count += 1
                        logger.debug(f"Обновлена статистика: {file_path.name}")
            
            stats['updated_files'] = updated_count
            
        except Exception as e:
            logger.error(f"Ошибка обновления статистики для {directory}: {e}")
            stats['error'] = str(e)
        
        return stats

    async def _discover_file(self, file_path: Path, delete_original: bool = False) -> Dict[str, Any]:
        """
        Асинхронное обнаружение одного файла
        
        Args:
            file_path: путь к файлу
            delete_original: режим удаления оригиналов
        
        Returns:
            Результат обнаружения файла
        """
        try:
            # Проверяем, новый ли файл
            existing_entry = self.store.get_file(file_path)
            is_new = existing_entry is None
            
            # Обнаруживаем файл через planner
            file_entry = await self.planner.discover_file(file_path, delete_original)
            
            return {
                'files_added': 1 if is_new else 0,
                'files_updated': 0 if is_new else 1,
                'file_entry': file_entry,
                'path': str(file_path)
            }
        except Exception as e:
            logger.error(f"Ошибка обнаружения файла {file_path}: {e}")
            return {'files_added': 0, 'files_updated': 0, 'error': str(e)}