"""Shared helpers for stock ledger tests."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.seeds.canon.models import DefectDecisionDef, ScrapPolicy
from app.models.section import Section
from app.stock import Reason, StockCommand, StockCommandService


# Fake canon data (ADR-0007): сервис не резолвит PlantConfig, данные приходят
# из composition root. Здесь — подмена для прямых вызовов в тестах.
# Тикет #132: политика брака передаётся одним объектом канона; find-or-create
# секции — шов scrap_policy.py.
FAKE_SCRAP_POLICY: dict = {"scrap_policy": ScrapPolicy()}

FAKE_DEFECT_DECISION_MAP: dict[str, DefectDecisionDef] = {
    "scrap": DefectDecisionDef(status="scrapped", reason="scrap"),
    "rework_current": DefectDecisionDef(status="rework_task_created", reason="rework"),
    "return_previous": DefectDecisionDef(status="rework_task_created", reason="return_to_previous"),
    "accept_with_deviation": DefectDecisionDef(status="accepted_with_deviation", reason="complete"),
}


async def record_transfer_receive(
    session: AsyncSession,
    *,
    product_id: int,
    from_location_id: int,
    to_location_id: int,
    quantity: Decimal,
    task_id: int,
    created_by: int,
    transfer_id: int | None = None,
) -> None:
    """Seed issued_quantity via TRANSFER_RECEIVE (auto-issue on receive)."""
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity=quantity,
            reason=Reason.TRANSFER_RECEIVE,
            task_id=task_id,
            transfer_id=transfer_id,
            created_by=created_by,
        ),
    )

async def canon_scrap_section_id(session: AsyncSession) -> int:
    """Id канонической SCRAP-секции по коду политики (#134).

    Харденинг find (code+type) означает: брак уходит на секцию канона,
    а не на первую попавшуюся SCRAP-секцию чужого кода из фикстуры.
    """
    scrap_id = await session.scalar(
        select(Section.id).where(Section.code == ScrapPolicy().code)
    )
    assert scrap_id is not None, "SCRAP-секция канона не найдена в тестовой БД"
    return scrap_id
