#!/usr/bin/env python3
"""
State Metrics - Сбор метрик и телеметрии для системы управления состояниями
Мини-телеметрия для мониторинга производительности и здоровья системы
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict, deque
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MetricEvent:
    """Событие метрики"""
    timestamp: float
    metric_name: str
    value: float = 1.0
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'metric_name': self.metric_name,
            'value': self.value,
            'tags': self.tags
        }


class StateMetrics:
    """Сборщик метрик для системы управления состояниями"""
    
    def __init__(self, retention_hours: int = 24, max_events: int = 10000):
        """
        Инициализация сборщика метрик
        
        Args:
            retention_hours: время хранения метрик в часах
            max_events: максимальное количество событий в памяти
        """
        self.retention_hours = retention_hours
        self.max_events = max_events
        
        # Хранилище событий (в памяти)
        self._events: deque[MetricEvent] = deque(maxlen=max_events)
        
        # Кеширование агрегатов для быстрого доступа
        self._cache = {}
        self._cache_expire = 0
        self._cache_ttl = 60  # кеш на минуту
        
        # Счетчики для основных метрик
        self._counters = defaultdict(float)
        
        logger.info(f"StateMetrics инициализирован (retention: {retention_hours}h, max_events: {max_events})")

    def record(self, metric_name: str, value: float = 1.0, tags: Dict[str, str] = None):
        """
        Запись события метрики
        
        Args:
            metric_name: имя метрики
            value: значение
            tags: теги для группировки
        """
        now = time.time()
        event = MetricEvent(
            timestamp=now,
            metric_name=metric_name,
            value=value,
            tags=tags or {}
        )
        
        self._events.append(event)
        self._counters[metric_name] += value
        
        # Сбрасываем кеш при новых данных
        self._cache_expire = 0
        
        logger.debug(f"Метрика записана: {metric_name}={value} {tags}")

    def increment(self, metric_name: str, tags: Dict[str, str] = None):
        """Увеличение счетчика на 1"""
        self.record(metric_name, 1.0, tags)

    def gauge(self, metric_name: str, value: float, tags: Dict[str, str] = None):
        """Запись значения gauge-метрики"""
        self.record(metric_name, value, tags)

    def timing(self, metric_name: str, duration_ms: float, tags: Dict[str, str] = None):
        """Запись времени выполнения в миллисекундах"""
        self.record(metric_name, duration_ms, tags)

    def _cleanup_old_events(self):
        """Удаление старых событий"""
        if not self._events:
            return
        
        cutoff_time = time.time() - (self.retention_hours * 3600)
        
        # Удаляем старые события с начала очереди
        while self._events and self._events[0].timestamp < cutoff_time:
            self._events.popleft()

    def _get_cached_or_compute(self, key: str, compute_func) -> Any:
        """Получение кешированного значения или вычисление нового"""
        now = time.time()
        
        if now > self._cache_expire:
            self._cache.clear()
            self._cache_expire = now + self._cache_ttl
        
        if key not in self._cache:
            self._cache[key] = compute_func()
        
        return self._cache[key]

    def get_counter(self, metric_name: str) -> float:
        """Получение значения счетчика"""
        return self._counters.get(metric_name, 0.0)

    def get_counters(self) -> Dict[str, float]:
        """Получение всех счетчиков"""
        return dict(self._counters)

    def get_events(self, metric_name: str = None, 
                  since_hours: float = None,
                  tags: Dict[str, str] = None) -> List[MetricEvent]:
        """
        Получение событий по критериям
        
        Args:
            metric_name: фильтр по имени метрики
            since_hours: события за последние N часов
            tags: фильтр по тегам
        
        Returns:
            Список событий
        """
        self._cleanup_old_events()
        
        events = list(self._events)
        
        # Фильтр по времени
        if since_hours is not None:
            cutoff_time = time.time() - (since_hours * 3600)
            events = [e for e in events if e.timestamp >= cutoff_time]
        
        # Фильтр по имени метрики
        if metric_name:
            events = [e for e in events if e.metric_name == metric_name]
        
        # Фильтр по тегам
        if tags:
            events = [
                e for e in events 
                if all(e.tags.get(k) == v for k, v in tags.items())
            ]
        
        return events

    def get_aggregate(self, metric_name: str, 
                     agg_func: str = 'sum',
                     since_hours: float = 1.0,
                     tags: Dict[str, str] = None) -> float:
        """
        Получение агрегированного значения метрики
        
        Args:
            metric_name: имя метрики
            agg_func: функция агрегации (sum, avg, min, max, count)
            since_hours: за последние N часов
            tags: фильтр по тегам
        
        Returns:
            Агрегированное значение
        """
        cache_key = f"{metric_name}_{agg_func}_{since_hours}_{hash(str(sorted((tags or {}).items())))}"
        
        def compute():
            events = self.get_events(metric_name, since_hours, tags)
            
            if not events:
                return 0.0
            
            values = [e.value for e in events]
            
            if agg_func == 'sum':
                return sum(values)
            elif agg_func == 'avg':
                return sum(values) / len(values)
            elif agg_func == 'min':
                return min(values)
            elif agg_func == 'max':
                return max(values)
            elif agg_func == 'count':
                return len(values)
            else:
                raise ValueError(f"Неизвестная функция агрегации: {agg_func}")
        
        return self._get_cached_or_compute(cache_key, compute)

    def get_rate(self, metric_name: str, 
                window_hours: float = 1.0,
                tags: Dict[str, str] = None) -> float:
        """
        Получение скорости метрики (события в час)
        
        Args:
            metric_name: имя метрики
            window_hours: окно для расчета скорости
            tags: фильтр по тегам
        
        Returns:
            События в час
        """
        events = self.get_events(metric_name, window_hours, tags)
        return len(events) / window_hours if window_hours > 0 else 0.0

    def get_summary(self, since_hours: float = 1.0) -> Dict[str, Any]:
        """
        Получение сводки метрик
        
        Args:
            since_hours: за последние N часов
        
        Returns:
            Сводка с основными метриками
        """
        self._cleanup_old_events()
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'since_hours': since_hours,
            'total_events': len(self._events),
            'counters': dict(self._counters),
            'metrics': {}
        }
        
        # Собираем уникальные имена метрик
        metric_names = set(e.metric_name for e in self._events)
        
        for metric_name in metric_names:
            metric_summary = {
                'count': self.get_aggregate(metric_name, 'count', since_hours),
                'sum': self.get_aggregate(metric_name, 'sum', since_hours),
                'rate_per_hour': self.get_rate(metric_name, since_hours)
            }
            
            # Добавляем avg, min, max если есть события
            if metric_summary['count'] > 0:
                metric_summary.update({
                    'avg': self.get_aggregate(metric_name, 'avg', since_hours),
                    'min': self.get_aggregate(metric_name, 'min', since_hours),
                    'max': self.get_aggregate(metric_name, 'max', since_hours)
                })
            
            summary['metrics'][metric_name] = metric_summary
        
        return summary

    def export_events(self, file_path: Path, since_hours: float = None):
        """
        Экспорт событий в JSON файл
        
        Args:
            file_path: путь к файлу
            since_hours: экспортировать события за последние N часов
        """
        events = self.get_events(since_hours=since_hours)
        
        data = {
            'exported_at': datetime.now().isoformat(),
            'since_hours': since_hours,
            'events_count': len(events),
            'events': [e.to_dict() for e in events]
        }
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Экспортировано {len(events)} событий в {file_path}")

    def reset(self):
        """Сброс всех метрик"""
        self._events.clear()
        self._counters.clear()
        self._cache.clear()
        logger.info("Метрики сброшены")


# === Глобальный экземпляр метрик ===
_global_metrics = None


def get_metrics() -> StateMetrics:
    """Получение глобального экземпляра метрик"""
    global _global_metrics
    if _global_metrics is None:
        # Создаем с дефолтными настройками, будет обновлено через init_metrics
        _global_metrics = StateMetrics()
    return _global_metrics


def init_metrics(retention_hours: int = 24, max_events: int = 10000) -> StateMetrics:
    """
    Инициализация глобальных метрик с конфигурацией
    
    Args:
        retention_hours: время хранения метрик в часах
        max_events: максимальное количество событий
    
    Returns:
        Настроенный экземпляр StateMetrics
    """
    global _global_metrics
    _global_metrics = StateMetrics(retention_hours=retention_hours, max_events=max_events)
    return _global_metrics


def record_metric(metric_name: str, value: float = 1.0, tags: Dict[str, str] = None):
    """Запись метрики в глобальный сборщик"""
    _global_metrics.record(metric_name, value, tags)


def increment_counter(metric_name: str, tags: Dict[str, str] = None):
    """Увеличение счетчика в глобальном сборщике"""
    _global_metrics.increment(metric_name, tags)


# === Константы метрик ===

class MetricNames:
    """Константы имен метрик"""
    
    # Обнаружение файлов
    FILES_DISCOVERED = "files_discovered"
    FILES_UPDATED = "files_updated" 
    FILES_REMOVED = "files_removed"
    
    # Проверка целостности
    INTEGRITY_CHECK = "integrity_check"  # базовое имя для MetricTimer
    INTEGRITY_CHECK_STARTED = "integrity_check_started"
    INTEGRITY_CHECK_COMPLETED = "integrity_check_completed"
    INTEGRITY_CHECK_FAILED = "integrity_check_failed"
    INTEGRITY_CHECK_DURATION_MS = "integrity_check_duration_ms"
    
    # Результаты проверки целостности
    INTEGRITY_PASS = "integrity_pass"
    INTEGRITY_FAIL = "integrity_fail"
    INTEGRITY_ERROR = "integrity_error"
    
    # Анализ аудио
    AUDIO_ANALYSIS_STARTED = "audio_analysis_started"
    AUDIO_ANALYSIS_COMPLETED = "audio_analysis_completed"
    AUDIO_ANALYSIS_FAILED = "audio_analysis_failed"
    AUDIO_ANALYSIS_DURATION_MS = "audio_analysis_duration_ms"
    
    # Результаты анализа аудио
    SKIPPED_EN2 = "skipped_en2"  # файлы с английской 2.0 дорожкой
    READY_FOR_CONVERSION = "ready_for_conversion"
    NO_SUITABLE_AUDIO = "no_suitable_audio"
    
    # Группы
    GROUPS_CREATED = "groups_created"
    GROUPS_UPDATED = "groups_updated"
    GROUPS_PAIRED = "groups_paired"
    PROCESSED_GROUPS = "processed_groups"
    
    # Система
    PLANNER_LOOP_DURATION_MS = "planner_loop_duration_ms"
    DUE_FILES_PROCESSED = "due_files_processed"
    STATE_ENTRIES_PRUNED = "state_entries_pruned"  # GC
    
    # Backoff и quarantine
    BACKOFF_APPLIED = "backoff_applied"
    BACKOFF_STARTED = "backoff_started"
    BACKOFF_RESUMED = "backoff_resumed"
    INTEGRITY_BACKOFF_STARTED = "integrity_backoff_started"
    INTEGRITY_BACKOFF_RESUMED = "integrity_backoff_resumed"
    INTEGRITY_FAIL_COUNT_MAX = "integrity_fail_count_max"
    QUARANTINED_FILES = "quarantined_files"
    QUARANTINED_TOTAL = "quarantined_total"  # Total count of quarantined files (Task 5)
    PENDING_RETRIES_TOTAL = "pending_retries_total"  # Total retry attempts (Task 5)
    SIZE_CHANGE_RESET = "size_change_reset"
    
    # Stability tracking (monotonic time based)
    STABILITY_ARMED = "stability_armed"
    STABILITY_DEFERRED = "stability_deferred" 
    STABILITY_TRIGGERED = "stability_triggered"
    
    # Ошибки
    STATE_STORE_ERRORS = "state_store_errors"
    PLANNER_ERRORS = "planner_errors"
    FILE_NOT_FOUND = "file_not_found"


# === Декоратор для измерения времени выполнения ===

def timed_metric(metric_name: str, tags: Dict[str, str] = None):
    """
    Декоратор для измерения времени выполнения функции
    
    Args:
        metric_name: имя метрики для записи времени
        tags: дополнительные теги
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                record_metric(f"{metric_name}_success", 1.0, tags)
                return result
            except Exception as e:
                record_metric(f"{metric_name}_error", 1.0, 
                            {**(tags or {}), 'error_type': type(e).__name__})
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                record_metric(f"{metric_name}_duration_ms", duration_ms, tags)
        
        # Для асинхронных функций
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    record_metric(f"{metric_name}_success", 1.0, tags)
                    return result
                except Exception as e:
                    record_metric(f"{metric_name}_error", 1.0,
                                {**(tags or {}), 'error_type': type(e).__name__})
                    raise
                finally:
                    duration_ms = (time.time() - start_time) * 1000
                    record_metric(f"{metric_name}_duration_ms", duration_ms, tags)
            return async_wrapper
        
        return wrapper
    return decorator


# === Контекстный менеджер для измерений ===

class MetricTimer:
    """Контекстный менеджер для измерения времени"""
    
    def __init__(self, metric_name: str, tags: Dict[str, str] = None):
        self.metric_name = metric_name
        self.tags = tags or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration_ms = (time.time() - self.start_time) * 1000
            
            if exc_type is None:
                record_metric(f"{self.metric_name}_success", 1.0, self.tags)
            else:
                record_metric(f"{self.metric_name}_error", 1.0, 
                            {**self.tags, 'error_type': exc_type.__name__})
            
            record_metric(f"{self.metric_name}_duration_ms", duration_ms, self.tags)