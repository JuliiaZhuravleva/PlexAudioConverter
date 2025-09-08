#!/usr/bin/env python3
"""
State Management Enums - Перечисления для управления состояниями
Единый словарь состояний для файловой системы и групп обработки
"""

from enum import Enum, auto
from typing import Dict, Set


class IntegrityStatus(Enum):
    """Статусы проверки целостности файлов"""
    UNKNOWN = "UNKNOWN"         # ещё не проверяли
    PENDING = "PENDING"         # проверка назначена/идёт  
    COMPLETE = "COMPLETE"       # можно доверять содержимому
    INCOMPLETE = "INCOMPLETE"   # проверка не прошла
    ERROR = "ERROR"             # сбой в проверке
    QUARANTINED = "QUARANTINED" # слишком много неудачных попыток, исключён из обработки

    def is_final(self) -> bool:
        """Является ли статус финальным (не требует дальнейших проверок)"""
        return self in {self.COMPLETE, self.INCOMPLETE, self.ERROR, self.QUARANTINED}

    def can_transition_to(self, target: 'IntegrityStatus') -> bool:
        """Может ли состояние перейти в целевое"""
        valid_transitions = {
            self.UNKNOWN: {self.PENDING, self.ERROR, self.QUARANTINED},
            self.PENDING: {self.COMPLETE, self.INCOMPLETE, self.ERROR, self.QUARANTINED},
            self.COMPLETE: {self.PENDING, self.ERROR},  # может потребоваться перепроверка
            self.INCOMPLETE: {self.PENDING, self.ERROR, self.QUARANTINED},
            self.ERROR: {self.PENDING, self.UNKNOWN, self.QUARANTINED},  # можно попробовать снова или исключить
            self.QUARANTINED: set()  # финальный статус, выхода нет
        }
        return target in valid_transitions.get(self, set())


class ProcessedStatus(Enum):
    """Статусы обработки файлов"""
    NEW = "NEW"                         # ещё ничего не делали
    SKIPPED_HAS_EN2 = "SKIPPED_HAS_EN2" # обнаружен англ. трек 2.0 — обработка не нужна
    CONVERTED = "CONVERTED"             # успешно сконвертирован
    CONVERT_FAILED = "CONVERT_FAILED"   # ошибка конвертации
    GROUP_PENDING_PAIR = "GROUP_PENDING_PAIR"  # ждём вторую копию в группе
    GROUP_PROCESSED = "GROUP_PROCESSED" # группа в финальном виде
    IGNORED = "IGNORED"                 # исключён правилами
    DUPLICATE = "DUPLICATE"             # дубликат того же group_id

    def is_final(self) -> bool:
        """Является ли статус финальным (не требует дальнейших действий)"""
        return self in {
            self.SKIPPED_HAS_EN2, self.CONVERTED, self.GROUP_PROCESSED, 
            self.IGNORED, self.DUPLICATE
        }

    def requires_conversion(self) -> bool:
        """Требует ли статус конвертации"""
        return self in {self.NEW}

    def can_transition_to(self, target: 'ProcessedStatus') -> bool:
        """Может ли состояние перейти в целевое"""
        valid_transitions = {
            self.NEW: {
                self.SKIPPED_HAS_EN2, self.CONVERTED, self.CONVERT_FAILED,
                self.GROUP_PENDING_PAIR, self.IGNORED, self.DUPLICATE
            },
            self.SKIPPED_HAS_EN2: {self.GROUP_PROCESSED},
            self.CONVERTED: {self.GROUP_PROCESSED},
            self.CONVERT_FAILED: {self.NEW, self.IGNORED},  # можно попробовать снова
            self.GROUP_PENDING_PAIR: {self.GROUP_PROCESSED, self.NEW},
            self.GROUP_PROCESSED: set(),  # финальный статус
            self.IGNORED: set(),          # финальный статус
            self.DUPLICATE: set()         # финальный статус
        }
        return target in valid_transitions.get(self, set())


class PairStatus(Enum):
    """Статусы групп файлов (original + .stereo)"""
    NONE = "NONE"                # один из файлов отсутствует
    WAITING_PAIR = "WAITING_PAIR"  # видим один, ждём второй
    PAIRED = "PAIRED"            # есть и original, и .stereo

    def can_transition_to(self, target: 'PairStatus') -> bool:
        """Может ли состояние перейти в целевое"""
        valid_transitions = {
            self.NONE: {self.WAITING_PAIR},
            self.WAITING_PAIR: {self.PAIRED, self.NONE},
            self.PAIRED: {self.WAITING_PAIR, self.NONE}
        }
        return target in valid_transitions.get(self, set())


class IntegrityMode(Enum):
    """Режимы проверки целостности"""
    QUICK = "QUICK"     # быстрая проверка (размер, заголовки)
    FULL = "FULL"       # полная проверка (чтение всего файла)
    AUTO = "AUTO"       # автоматический выбор режима


class GroupProcessedStatus(Enum):
    """Статусы обработки групп файлов"""
    NEW = "NEW"                 # новая группа
    GROUP_PROCESSED = "GROUP_PROCESSED"  # группа полностью обработана
    PARTIAL = "PARTIAL"         # частично обработана
    ERROR = "ERROR"             # ошибка в группе


# Вспомогательные функции для валидации переходов
def validate_integrity_transition(current: IntegrityStatus, target: IntegrityStatus) -> bool:
    """Проверяет корректность перехода статуса целостности"""
    if current == target:
        return True
    return current.can_transition_to(target)


def validate_processed_transition(current: ProcessedStatus, target: ProcessedStatus) -> bool:
    """Проверяет корректность перехода статуса обработки"""
    if current == target:
        return True
    return current.can_transition_to(target)


def validate_pair_transition(current: PairStatus, target: PairStatus) -> bool:
    """Проверяет корректность перехода статуса группы"""
    if current == target:
        return True
    return current.can_transition_to(target)


# Константы для удобства
INTEGRITY_FINAL_STATES = {
    IntegrityStatus.COMPLETE, 
    IntegrityStatus.INCOMPLETE, 
    IntegrityStatus.ERROR
}

PROCESSED_FINAL_STATES = {
    ProcessedStatus.SKIPPED_HAS_EN2,
    ProcessedStatus.CONVERTED, 
    ProcessedStatus.GROUP_PROCESSED,
    ProcessedStatus.IGNORED,
    ProcessedStatus.DUPLICATE
}

PROCESSED_ERROR_STATES = {
    ProcessedStatus.CONVERT_FAILED
}