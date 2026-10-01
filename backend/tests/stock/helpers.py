"""Shared helpers for stock ledger tests."""

from __future__ import annotations

from decimal import Decimal

from app.models.section import Section
from app.models.work_task import WorkTask
from app.seeds.canon.models import DefectDecisionDef, ScrapPolicy
from app.services.material_operations import (
    completed_operations_for_task,
    previous_stage_sequence,
)
from app.stock import Reason, StockCommand, StockCommandService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def seed_stock_for_task(
    session: AsyncSession,
    *,
    product_id: int,
    task: WorkTask,
    quantity: Decimal,
    created_by: int,
    location_id: int | None = None,
    dimensions: dict | None = None,
    through_previous_stage: bool = False,
) -> StockCommand:
    """Приход остатка в ту ops-группу, которую потом спишет ``task``.

    ADR-0055: списание точное — расход уменьшает строку баланса с тем же
    признаком операций, что и у команды. ``record()`` выводит признак
    плановой проводки из маршрута задания, поэтому наивный
    ``MANUAL_IN`` без признака лёг бы в ``NULL``-группу, а последующее
    план-driven списание искало бы ops-группу маршрута и получало
    «available 0». Здесь признак берётся из того же источника, что и у
    списания: ``completed_operations_for_task``.

    ``through_previous_stage=True`` — для прихода материала, который на
    секцию этапа попал ДО его собственных операций (вход трансформации,
    возврат остатка): там списание идёт по признаку до предыдущего этапа.
    """
    through_sequence = None
    if through_previous_stage:
        previous_sequence = await previous_stage_sequence(session, task)
        through_sequence = previous_sequence if previous_sequence is not None else 0
    ops = await completed_operations_for_task(
        session, task, through_sequence=through_sequence
    )
    assert ops is not None, (
        f"маршрут задания #{task.id} не разрешён в ops-признак — "
        "такое задание нельзя засеять реалистичным остатком"
    )
    svc = StockCommandService()
    return await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id if location_id is not None else task.section_id,
            quantity=quantity,
            reason=Reason.MANUAL_IN,
            dimensions=dimensions,
            completed_operations=ops,
            created_by=created_by,
        ),
    )


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
    completed_operations: list[str] | None = None,
) -> None:
    """Seed issued_quantity via TRANSFER_RECEIVE (auto-issue on receive).

    ``completed_operations`` по умолчанию ``None`` — тогда ``record()``
    выведет признак из маршрута задания, как в бою. Значение передаётся
    явно там, где приёмная секция получает материал, пришедший с
    ПРЕДЫДУЩЕГО этапа: такой материал лежит в ops-группе «до своего этапа»,
    и списание (возврат остатка, ``return_previous``) ищет именно её.
    """
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
            completed_operations=completed_operations,
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
