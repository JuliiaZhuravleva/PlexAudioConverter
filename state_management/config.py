#!/usr/bin/env python3
"""
State Configuration - Управление конфигурацией системы состояний
Централизованная настройка всех компонентов state management
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, asdict, field
import os

logger = logging.getLogger(__name__)


@dataclass
class StateConfig:
    """Конфигурация системы управления состояниями"""
    
    # === Общие настройки ===
    
    # База данных
    storage_url: str = "state.db"
    
    # Стабильность файлов
    stable_wait_sec: int = 30
    
    # Backoff для повторных попыток
    backoff_step_sec: int = 30
    backoff_max_sec: int = 600
    quarantine_threshold: int = 5  # После этого количества неудач файл помечается как QUARANTINED
    
    # Ограничения памяти
    max_state_entries: int = 5000
    keep_processed_days: int = 30
    
    # === Планировщик ===
    
    # Размер пакета для обработки файлов
    batch_size: int = 50
    
    # Интервал основного цикла (секунды)
    loop_interval_sec: int = 5
    
    # Максимальная глубина сканирования директорий
    max_scan_depth: int = 3
    
    # Максимальное количество одновременных discovery операций
    max_concurrent_discovery: int = 10
    
    # === Проверка целостности ===
    
    # Быстрый или полный режим проверки
    integrity_quick_mode: bool = True
    
    # Таймаут для проверки целостности (секунды)
    integrity_timeout_sec: int = 300
    
    # Минимальный размер файла для проверки (байты)
    min_file_size: int = 1024 * 1024  # 1MB
    
    # Максимальный размер файла для быстрой проверки (байты)
    quick_check_max_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    
    # === Аудио обработка ===
    
    # Пути к утилитам
    ffprobe_path: str = "ffprobe"
    ffmpeg_path: str = "ffmpeg"
    
    # Поддерживаемые видео форматы (включая временные расширения для отслеживания переименований)
    video_extensions: list = field(default_factory=lambda: [
        '.mp4', '.mkv', '.avi', '.mov', '.m4v', '.wmv', '.flv', '.webm',
        '.tmp', '.part', '.download'  # Temporary extensions for rename tracking
    ])
    
    # Настройки конвертации (будут использоваться в следующих версиях)
    audio_codec: str = 'aac'
    audio_bitrate: str = '192k'
    audio_sample_rate: str = '48000'
    
    # === Метрики ===
    
    # Включить сбор метрик
    metrics_enabled: bool = True
    
    # Время хранения метрик (часы)
    metrics_retention_hours: int = 24
    
    # Максимальное количество событий метрик в памяти
    max_metric_events: int = 10000
    
    # Экспорт метрик в файл
    metrics_export_path: Optional[str] = None
    metrics_export_interval_hours: int = 6
    
    # === Логирование ===
    
    # Уровень логирования для state компонентов
    state_log_level: str = "INFO"
    
    # Логирование в файл
    state_log_file: Optional[str] = "state_manager.log"
    
    # === Производительность ===
    
    # Количество worker'ов для параллельной обработки
    worker_threads: int = 2
    
    # Использовать connection pooling для БД
    db_connection_pool: bool = True
    
    # Размер пула подключений
    db_pool_size: int = 5
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StateConfig':
        """Создание из словаря"""
        # Фильтруем неизвестные ключи
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)
    
    def validate(self) -> bool:
        """Валидация конфигурации"""
        errors = []
        
        # Проверяем временные параметры
        if self.stable_wait_sec < 1:
            errors.append("stable_wait_sec должен быть >= 1")
        
        if self.backoff_step_sec < 1:
            errors.append("backoff_step_sec должен быть >= 1")
        
        if self.backoff_max_sec < self.backoff_step_sec:
            errors.append("backoff_max_sec должен быть >= backoff_step_sec")
        
        if self.quarantine_threshold < 2:
            errors.append("quarantine_threshold должен быть >= 2")
        
        # Проверяем лимиты
        if self.max_state_entries < 100:
            errors.append("max_state_entries должен быть >= 100")
        
        if self.batch_size < 1:
            errors.append("batch_size должен быть >= 1")
        
        # Проверяем пути к утилитам
        if not self.ffprobe_path:
            errors.append("ffprobe_path не может быть пустым")
        
        if not self.video_extensions:
            errors.append("video_extensions не может быть пустым")
        
        # Проверяем уровень логирования
        valid_log_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if self.state_log_level.upper() not in valid_log_levels:
            errors.append(f"state_log_level должен быть одним из: {valid_log_levels}")
        
        if errors:
            for error in errors:
                logger.error(f"Ошибка валидации конфигурации: {error}")
            return False
        
        return True
    
    def update_from_env(self) -> 'StateConfig':
        """Обновление конфигурации из переменных окружения"""
        env_mappings = {
            'STATE_STORAGE_URL': 'storage_url',
            'STATE_STABLE_WAIT_SEC': ('stable_wait_sec', int),
            'STATE_BACKOFF_STEP_SEC': ('backoff_step_sec', int),
            'STATE_BACKOFF_MAX_SEC': ('backoff_max_sec', int),
            'STATE_MAX_ENTRIES': ('max_state_entries', int),
            'STATE_BATCH_SIZE': ('batch_size', int),
            'STATE_LOOP_INTERVAL': ('loop_interval_sec', int),
            'STATE_INTEGRITY_QUICK': ('integrity_quick_mode', lambda x: x.lower() == 'true'),
            'STATE_INTEGRITY_TIMEOUT': ('integrity_timeout_sec', int),
            'STATE_FFPROBE_PATH': 'ffprobe_path',
            'STATE_FFMPEG_PATH': 'ffmpeg_path',
            'STATE_METRICS_ENABLED': ('metrics_enabled', lambda x: x.lower() == 'true'),
            'STATE_LOG_LEVEL': 'state_log_level',
            'STATE_LOG_FILE': 'state_log_file',
            'STATE_WORKER_THREADS': ('worker_threads', int)
        }
        
        for env_key, mapping in env_mappings.items():
            env_value = os.getenv(env_key)
            if env_value is None:
                continue
            
            if isinstance(mapping, tuple):
                attr_name, converter = mapping
                try:
                    setattr(self, attr_name, converter(env_value))
                    logger.debug(f"Обновлена настройка из env {env_key}: {attr_name} = {env_value}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Не удалось преобразовать {env_key}={env_value}: {e}")
            else:
                attr_name = mapping
                setattr(self, attr_name, env_value)
                logger.debug(f"Обновлена настройка из env {env_key}: {attr_name} = {env_value}")
        
        return self


class StateConfigManager:
    """Менеджер конфигурации системы состояний"""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """
        Инициализация менеджера конфигурации
        
        Args:
            config_path: путь к файлу конфигурации
        """
        self.config_path = Path(config_path) if config_path else None
        self._config: Optional[StateConfig] = None
        
        logger.info(f"StateConfigManager инициализирован (config: {config_path})")
    
    def load_config(self, reload: bool = False) -> StateConfig:
        """
        Загрузка конфигурации
        
        Args:
            reload: принудительная перезагрузка
        
        Returns:
            Объект конфигурации
        """
        if self._config is not None and not reload:
            return self._config
        
        # Начинаем с дефолтной конфигурации
        config = StateConfig()
        
        # Загружаем из файла если указан
        if self.config_path and self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                config = StateConfig.from_dict(config_data)
                logger.info(f"Конфигурация загружена из файла: {self.config_path}")
                
            except Exception as e:
                logger.error(f"Ошибка загрузки конфигурации из {self.config_path}: {e}")
                logger.info("Используется дефолтная конфигурация")
        
        # Обновляем из переменных окружения
        config.update_from_env()
        
        # Валидируем конфигурацию
        if not config.validate():
            raise ValueError("Конфигурация не прошла валидацию")
        
        self._config = config
        return config
    
    def save_config(self, config: Optional[StateConfig] = None):
        """
        Сохранение конфигурации в файл
        
        Args:
            config: конфигурация для сохранения (по умолчанию - текущая)
        """
        if not self.config_path:
            raise ValueError("config_path не задан")
        
        if config is None:
            config = self.get_config()
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            
            logger.info(f"Конфигурация сохранена в {self.config_path}")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации в {self.config_path}: {e}")
            raise
    
    def get_config(self) -> StateConfig:
        """Получение текущей конфигурации"""
        if self._config is None:
            return self.load_config()
        return self._config
    
    def update_config(self, updates: Dict[str, Any]) -> StateConfig:
        """
        Обновление конфигурации
        
        Args:
            updates: словарь с обновлениями
        
        Returns:
            Обновленная конфигурация
        """
        config = self.get_config()
        
        # Применяем обновления
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
                logger.debug(f"Обновлена настройка: {key} = {value}")
            else:
                logger.warning(f"Неизвестная настройка: {key}")
        
        # Валидируем обновленную конфигурацию
        if not config.validate():
            raise ValueError("Обновленная конфигурация не прошла валидацию")
        
        return config
    
    def create_sample_config(self, output_path: Union[str, Path]):
        """
        Создание примера конфигурации
        
        Args:
            output_path: путь для сохранения примера
        """
        sample_config = StateConfig()
        
        # Добавляем комментарии в JSON
        config_dict = sample_config.to_dict()
        
        # Создаем документированный JSON
        documented_config = {
            "__comment_general": "=== Общие настройки ===",
            "storage_url": config_dict["storage_url"],
            "stable_wait_sec": config_dict["stable_wait_sec"],
            "backoff_step_sec": config_dict["backoff_step_sec"],
            "backoff_max_sec": config_dict["backoff_max_sec"],
            "max_state_entries": config_dict["max_state_entries"],
            "keep_processed_days": config_dict["keep_processed_days"],
            
            "__comment_planner": "=== Планировщик ===",
            "batch_size": config_dict["batch_size"],
            "loop_interval_sec": config_dict["loop_interval_sec"],
            "max_scan_depth": config_dict["max_scan_depth"],
            "max_concurrent_discovery": config_dict["max_concurrent_discovery"],
            
            "__comment_integrity": "=== Проверка целостности ===",
            "integrity_quick_mode": config_dict["integrity_quick_mode"],
            "integrity_timeout_sec": config_dict["integrity_timeout_sec"],
            "min_file_size": config_dict["min_file_size"],
            "quick_check_max_size": config_dict["quick_check_max_size"],
            
            "__comment_audio": "=== Аудио обработка ===",
            "ffprobe_path": config_dict["ffprobe_path"],
            "ffmpeg_path": config_dict["ffmpeg_path"],
            "video_extensions": config_dict["video_extensions"],
            "audio_codec": config_dict["audio_codec"],
            "audio_bitrate": config_dict["audio_bitrate"],
            "audio_sample_rate": config_dict["audio_sample_rate"],
            
            "__comment_metrics": "=== Метрики ===",
            "metrics_enabled": config_dict["metrics_enabled"],
            "metrics_retention_hours": config_dict["metrics_retention_hours"],
            "max_metric_events": config_dict["max_metric_events"],
            "metrics_export_path": config_dict["metrics_export_path"],
            "metrics_export_interval_hours": config_dict["metrics_export_interval_hours"],
            
            "__comment_logging": "=== Логирование ===",
            "state_log_level": config_dict["state_log_level"],
            "state_log_file": config_dict["state_log_file"],
            
            "__comment_performance": "=== Производительность ===",
            "worker_threads": config_dict["worker_threads"],
            "db_connection_pool": config_dict["db_connection_pool"],
            "db_pool_size": config_dict["db_pool_size"]
        }
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(documented_config, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Пример конфигурации создан: {output_path}")


# === Глобальный менеджер конфигурации ===
_global_config_manager: Optional[StateConfigManager] = None


def init_config(config_path: Optional[Union[str, Path]] = None) -> StateConfigManager:
    """
    Инициализация глобального менеджера конфигурации
    
    Args:
        config_path: путь к файлу конфигурации
    
    Returns:
        Менеджер конфигурации
    """
    global _global_config_manager
    _global_config_manager = StateConfigManager(config_path)
    return _global_config_manager


def get_config_manager() -> StateConfigManager:
    """Получение глобального менеджера конфигурации"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = StateConfigManager()
    return _global_config_manager


def get_config() -> StateConfig:
    """Получение текущей конфигурации"""
    return get_config_manager().get_config()


# === Утилиты для настройки логирования ===

def setup_logging(config: StateConfig):
    """Настройка логирования согласно конфигурации"""
    # Настройка уровня логирования для state компонентов
    state_logger = logging.getLogger('state_management')
    state_logger.setLevel(getattr(logging, config.state_log_level.upper()))
    
    # Удаляем существующие файловые handlers чтобы избежать дублирования
    for handler in state_logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            state_logger.removeHandler(handler)
            handler.close()
    
    # Добавляем файловый handler если указан
    if config.state_log_file:
        log_path = Path(config.state_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(getattr(logging, config.state_log_level.upper()))
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        state_logger.addHandler(file_handler)
        
        logger.info(f"Логирование state компонентов настроено (файл: {log_path})")


# === Дефолтные конфигурации для разных сценариев ===

def get_development_config() -> StateConfig:
    """Конфигурация для разработки"""
    return StateConfig(
        storage_url="dev_state.db",
        stable_wait_sec=5,  # быстрее для тестирования
        batch_size=10,
        loop_interval_sec=2,
        integrity_quick_mode=True,
        metrics_enabled=True,
        state_log_level="DEBUG"
    )


def get_production_config() -> StateConfig:
    """Конфигурация для продакшена"""
    return StateConfig(
        storage_url="state.db",
        stable_wait_sec=30,
        batch_size=100,
        loop_interval_sec=5,
        integrity_quick_mode=False,
        max_state_entries=10000,
        keep_processed_days=90,
        metrics_enabled=True,
        state_log_level="INFO",
        worker_threads=4
    )