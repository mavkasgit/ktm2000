#!/usr/bin/env python
"""Сверка persisted-кэшей ``SectionPlanLine`` с нетто-ledger.

После перехода проекций COMPLETE/SCRAP на ``net_quantity_expr()`` (откат
завершения вычитается) старые строки ``section_plan_lines`` могли остаться
с gross-значениями: кэш пересчитывается при следующем действии по строке,
но если действий больше не было — ``cached_completed_quantity`` /
``cached_rejected_quantity`` удвоены после ``reverse(task_complete)``.

Скрипт только читает и сравнивает. ``--apply`` пересчитывает найденные
строки тем же production-кодом (``_refresh_section_plan_line_cache``).
Миграции и структура БД не меняются.

Запуск (из ``backend/``):

    python scripts/audit_section_plan_line_caches.py           # dry-run, exit 1 при расхождениях
    python scripts/audit_section_plan_line_caches.py --apply   # пересчитать
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask
from app.services.shopfloor.cache import _refresh_section_plan_line_cache
from app.stock.ledger import net_quantity_expr
from app.stock.models import Reason, StockTransaction
from sqlalchemy import func, select


@dataclass(frozen=True)
class StaleLineCache:
    line_id: int
    cached_completed: Decimal
    net_completed: Decimal
    cached_rejected: Decimal
    net_rejected: Decimal

    @property
    def fields(self) -> str:
        fields: list[str] = []
        if self.cached_completed != self.net_completed:
            fields.append(
                f"completed {self.cached_completed} -> {self.net_completed}"
            )
        if self.cached_rejected != self.net_rejected:
            fields.append(f"rejected {self.cached_rejected} -> {self.net_rejected}")
        return ", ".join(fields)


def _dec(value) -> Decimal:
    return Decimal(value or 0)


async def find_stale_caches(db) -> list[StaleLineCache]:
    """Вернуть строки, где persisted COMPLETE/SCRAP не равны нетто-ledger."""
    lines = (
        await db.execute(select(SectionPlanLine.id).order_by(SectionPlanLine.id))
    ).scalars().all()
    if not lines:
        return []

    rows = (
        await db.execute(
            select(
                WorkTask.section_plan_line_id,
                StockTransaction.reason,
                func.coalesce(func.sum(net_quantity_expr()), 0),
            )
            .join(StockTransaction, StockTransaction.task_id == WorkTask.id)
            .where(
                WorkTask.section_plan_line_id.in_(lines),
                StockTransaction.reason.in_([Reason.COMPLETE, Reason.SCRAP]),
            )
            .group_by(WorkTask.section_plan_line_id, StockTransaction.reason)
        )
    ).all()
    net: dict[int, dict[Reason, Decimal]] = {}
    for line_id, reason, qty in rows:
        net.setdefault(line_id, {})[reason] = _dec(qty)

    stale: list[StaleLineCache] = []
    for line in (
        await db.execute(
            select(SectionPlanLine).where(SectionPlanLine.id.in_(lines))
        )
    ).scalars():
        sums = net.get(line.id, {})
        net_completed = sums.get(Reason.COMPLETE, Decimal(0))
        net_rejected = sums.get(Reason.SCRAP, Decimal(0))
        cached_completed = _dec(line.cached_completed_quantity)
        cached_rejected = _dec(line.cached_rejected_quantity)
        if (
            cached_completed != net_completed
            or cached_rejected != net_rejected
        ):
            stale.append(
                StaleLineCache(
                    line_id=line.id,
                    cached_completed=cached_completed,
                    net_completed=net_completed,
                    cached_rejected=cached_rejected,
                    net_rejected=net_rejected,
                )
            )
    return stale


async def refresh_stale_caches(db, stale: list[StaleLineCache]) -> None:
    """Пересчитать кэш каждой найденной строки production-кодом и закоммитить."""
    for item in stale:
        await _refresh_section_plan_line_cache(db, item.line_id)
    await db.commit()


async def _run(apply: bool) -> int:
    async with async_session() as db:
        stale = await find_stale_caches(db)
        if not stale:
            print("OK: persisted-кэши SectionPlanLine совпадают с нетто-ledger")
            return 0

        print(f"Найдено расхождений: {len(stale)}")
        for item in stale[:20]:
            print(f"  line {item.line_id}: {item.fields}")
        if len(stale) > 20:
            print(f"  ... и ещё {len(stale) - 20}")

        if not apply:
            print("Dry-run: запустите с --apply, чтобы пересчитать строки")
            return 1

        await refresh_stale_caches(db, stale)
        remaining = await find_stale_caches(db)
        if remaining:
            print(f"ОШИБКА: после пересчёта осталось расхождений: {len(remaining)}")
            return 1
        print(f"Пересчитано строк: {len(stale)}")
        return 0


def main() -> int:
    return asyncio.run(_run(apply="--apply" in sys.argv))


if __name__ == "__main__":
    sys.exit(main())
