"""Строки по выходам трансформирующей задачи — единый владелец сборки
«план / сделано / использовано / остаток» на каждый выход (тикет #125).

Поверх примитивов ``operations_transform`` (``build_outputs_progress`` +
``distribute_output_quantities``): оба распределения идут по ОДНОМУ списку
outputs одним алгоритмом последовательного заполнения, поэтому zip двух
независимых вызовов в потребителях больше не нужен.

Выбор смысла бюджета (``remaining_send`` vs ``remaining_transform``)
остаётся у потребителя (grilling #119 Q1a/Q6a) — модуль бюджет не применяет.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.shopfloor.operations_transform import (
    build_outputs_progress,
    distribute_output_quantities,
    get_transform_progress,
)
from app.stock.ledger import net_by_reason_by_dimensions
from app.stock.models import Reason


@dataclass(frozen=True)
class OutputRow:
    """Строка одного выхода спецификации: план/сделано/использовано/остаток."""

    row_number: int | None          # из entry.outputs
    dimensions: dict | None         # каноническая форма
    quantity: Decimal               # план строки выхода
    produced_quantity: Decimal      # произведено по размеру (последоват. разливка)
    used_quantity: Decimal          # передано/выпущено по размеру (та же разливка)

    @property
    def remaining_quantity(self) -> Decimal:
        """Остаток выхода: max(0, произведено − использовано)."""
        return max(Decimal("0"), self.produced_quantity - self.used_quantity)


def build_output_rows(
    outputs: list[dict],
    produced_by_group: dict[str | None, Decimal],
    used_by_group: dict[str | None, Decimal],
) -> list[OutputRow]:
    """Собрать строку на каждый выход спецификации.

    Произведённое и использованное распределяются по строкам одного размера
    последовательно (первая строка заполняется первой) — два выхода одного
    размера не делят один бюджет дважды (тикет #91).
    """
    produced_rows = build_outputs_progress(outputs, produced_by_group)
    used_rows = distribute_output_quantities(outputs, used_by_group)
    return [
        OutputRow(
            row_number=produced["row_number"],
            dimensions=produced["dimensions"],
            quantity=produced["quantity"],
            produced_quantity=produced["produced_quantity"],
            used_quantity=used,
        )
        for produced, used in zip(produced_rows, used_rows)
    ]


class UsedSource(Enum):
    """Смысл «использованного» бюджета по размерам (выбирает потребитель)."""

    NET_TRANSFERRED = Reason.TRANSFER_SEND   # net_transferred_by_dimensions (нефинальный участок)
    NET_FINAL_RELEASE = Reason.FINAL_RELEASE # net_by_reason_by_dimensions(FINAL_RELEASE)


async def get_used_by_group(
    db: AsyncSession, *, task_id: int, source: UsedSource,
) -> dict[str | None, Decimal]:
    """Групповой net выбранного источника: {hash_key(габарит): количество}."""
    return await net_by_reason_by_dimensions(
        db, reason=source.value, task_id=task_id,
    )


async def build_task_output_rows(
    db: AsyncSession,
    *,
    task_id: int,
    outputs: list[dict],
    used_source: UsedSource,
) -> list[OutputRow]:
    """get_transform_progress + get_used_by_group + build_output_rows одним вызовом."""
    progress = await get_transform_progress(db, task_id)
    used_by_group = await get_used_by_group(db, task_id=task_id, source=used_source)
    return build_output_rows(outputs, progress.produced_by_group, used_by_group)
