"""Чистые функции проекции количеств задачи из ledger StockTransaction."""

from __future__ import annotations

from decimal import Decimal


def effective_issued_quantity(*, received: Decimal) -> Decimal:
    """Сколько материала выдано в работу по заданию.

    Единственный канал после миграции на Transfer: net ``TRANSFER_RECEIVE``
    по заданию. Исторические ``ISSUE_TO_WORK`` в БД не участвуют в проекции.
    """
    return received


def compute_task_available(
    *,
    planned_quantity: Decimal,
    received_quantity: Decimal,
    issued_quantity: Decimal,
    returned_quantity: Decimal,
    is_first_stage: bool,
) -> Decimal:
    base_available = planned_quantity if is_first_stage else Decimal("0")
    available = base_available + received_quantity + returned_quantity - issued_quantity
    return available if available > Decimal("0") else Decimal("0")


def compute_remaining(*, planned_quantity: Decimal, transferred_quantity: Decimal) -> Decimal:
    remaining = planned_quantity - transferred_quantity
    return remaining if remaining > Decimal("0") else Decimal("0")