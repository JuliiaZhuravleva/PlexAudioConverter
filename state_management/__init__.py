#!/usr/bin/env python3
"""
State Management System - Система управления состояниями файлов
Единое state-хранилище и словарь состояний для детерминизма и предсказуемых переходов
"""

from .enums import IntegrityStatus, ProcessedStatus, PairStatus, IntegrityMode
from .models import FileEntry, GroupEntry, normalize_group_id
from .store import StateStore
from .planner import StatePlanner
from .machine import AudioStateMachine, create_state_machine
from .config import StateConfig, StateConfigManager, get_config, init_config
from .metrics import get_metrics, MetricNames
from .manager import StateManager, create_state_manager

__version__ = "1.0.0"
__author__ = "Assistant"

# Основной API
__all__ = [
    # Главные классы
    'StateManager',
    'AudioStateMachine', 
    'StateStore',
    'StatePlanner',
    
    # Модели данных
    'FileEntry',
    'GroupEntry',
    'StateConfig',
    
    # Перечисления
    'IntegrityStatus',
    'ProcessedStatus', 
    'PairStatus',
    'IntegrityMode',
    
    # Фабричные функции
    'create_state_manager',
    'create_state_machine',
    
    # Конфигурация
    'init_config',
    'get_config',
    
    # Метрики
    'get_metrics',
    'MetricNames',
    
    # Утилиты
    'normalize_group_id'
]