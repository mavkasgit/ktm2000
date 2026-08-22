"""Общий интерфейс компенсаторов и структуры плана отката (ADR-0019).

Компенсатор — доменный специалист, знающий, как отменить действие своего
типа. Единственный способ отката — компенсирующие записи (ledger
append-only), связанные с исходными через ``reverses_id``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.stock.models import QualityState, Reason


@dataclass
class CheckBlocker:
    """Структурированный блокер проверки отката."""

    kind: str  # not_found | already_reversed | coverage | domain_cancelled
    detail: str
    deficit: Decimal | None = None


@dataclass
class ReversalCheck:
    """Результат проверки возможности отката действия."""

    node_id: int | None
    ok: bool
    blockers: list[CheckBlocker] = field(default_factory=list)
    deficit: Decimal | None = None


@dataclass
class PlannedEntry:
    """Зеркальная проводка 1:1 (ADR-0019 п.4, без партионности)."""

    source_tx_id: int
    product_id: int
    # Геометрия КОМПЕНСАЦИИ: локации уже перевёрнуты относительно исходной.
    from_location_id: int | None
    to_location_id: int | None
    quantity: Decimal
    dimensions: dict | None
    reason: Reason
    quality_state: QualityState
    to_quality_state: QualityState | None = None
    task_id: int | None = None
    transfer_id: int | None = None
    section_plan_line_id: int | None = None
    is_post_factum: bool = False

    # Автор исходной проводки — fallback для created_by компенсации.
    created_by: int | None = None
@dataclass
class ReversalPlan:
    """План отката одного действия: список зеркальных проводок."""

    action_id: int
    action_type: str
    ref_id: int | None
    hard: bool
    entries: list[PlannedEntry] = field(default_factory=list)
    # Проставляется ReversalService перед apply: проводки отката
    # ссылаются на запись Action типа reversal.
    reversal_action_id: int | None = None
    actor_id: int | None = None
    actor_name: str | None = None
    comment: str | None = None


@dataclass
class ReversalResult:
    """Результат применения компенсаций одного действия."""

    action_id: int
    reversal_action_id: int
    compensated_tx_ids: list[int] = field(default_factory=list)
    # Идентификаторы отменённых действий (при каскаде — в порядке исполнения).
    reversed_action_ids: list[int] = field(default_factory=list)


class Compensator(Protocol):
    """Контракт доменного компенсатора (ADR-0019 п.3/4)."""

    action_type: str

    async def check(self, db: AsyncSession, ref_id: int | None) -> ReversalCheck:
        """Проверить возможность отката без исполнения."""
        ...

    async def plan(self, db: AsyncSession, ref_id: int | None, *, hard: bool) -> ReversalPlan:
        """Построить план компенсаций (без записи в ledger)."""
        ...

    async def apply(self, db: AsyncSession, plan: ReversalPlan, actor: str) -> ReversalResult:
        """Исполнить план атомарно (в текущей транзакции сессии)."""
        ...
