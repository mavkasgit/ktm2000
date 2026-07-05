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


def resolve_work_task_status(
    *,
    current_status: str,
    planned_quantity: Decimal,
    remaining_quantity: Decimal,
    transferred_quantity: Decimal,
    completed_quantity: Decimal,
    rejected_quantity: Decimal,
    issued_quantity: Decimal,
    received_quantity: Decimal,
) -> str | None:
    """Вывести целевой статус WorkTask из проекции ledger.

    Возвращает новый статус или None, если переход не требуется.
    """
    if current_status in ("completed", "cancelled"):
        return None
    if planned_quantity <= Decimal("0"):
        return None

    if current_status == "waiting_previous":
        return "ready" if received_quantity > Decimal("0") else None

    active_statuses = {"ready", "in_progress", "partially_completed"}
    if current_status not in active_statuses:
        return None

    if remaining_quantity <= Decimal("0") and transferred_quantity >= planned_quantity:
        return "completed"

    produced = completed_quantity + rejected_quantity
    if produced > Decimal("0") and produced < planned_quantity:
        return "partially_completed"

    if (issued_quantity > Decimal("0") or produced > Decimal("0")) and current_status == "ready":
        return "in_progress"

    return None