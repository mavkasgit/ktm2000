"""Общий шов идемпотентности (ADR-0022, тикет #135).

Unique-бэкстоп на ``idempotency_key`` ловит гонку SELECT-then-INSERT на
уровне БД; ``is_idempotency_violation`` отличает IntegrityError именно от
этого индекса от чужих констрейнтов (FK, CHECK), которые должны
продолжать всплывать как есть.
"""
from __future__ import annotations

from typing import NoReturn

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import IdempotencyConflict


def is_idempotency_violation(exc: IntegrityError, index_name: str) -> bool:
    """IntegrityError именно от unique-индекса идемпотентности ``index_name``."""
    orig = exc.orig
    constraint = getattr(orig, "constraint_name", None) or getattr(
        orig, "constraint", None
    )
    return index_name in str(constraint or orig)


def raise_idempotency_conflict_on_violation(
    exc: IntegrityError,
    *,
    index_name: str,
    entity: str,
    idempotency_key: str | None,
) -> NoReturn:
    """Перевести flush-гонку в 409 или пробросить чужой IntegrityError.

    Всегда бросает: IntegrityError от unique-индекса идемпотентности —
    как ``IdempotencyConflict`` (KTMException, не ValueError: shopfloor-
    роуты переводят ValueError в 400); любой другой — как есть.

    ``idempotency_key=None`` сюда фактически не доезжает — partial unique
    не ловит NULL-ключи; параметр остаётся optional для типовой
    совместимости с сервисными сигнатурами.
    """
    if not is_idempotency_violation(exc, index_name):
        raise exc
    raise IdempotencyConflict(entity, idempotency_key or "") from exc
