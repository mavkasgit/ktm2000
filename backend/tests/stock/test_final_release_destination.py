"""Адресат FINAL_RELEASE по маршруту (тикет #137).

Каскад (гриллинг 2026-09-05):
1. Складский (transit) хоп маршрута задачи, следующий за финальным этапом.
2. Глобальный дефолт «склад выпуска» — секция с ``is_output_default``.
3. Неоднозначность/отсутствие адресата → отказ операции (ValueError).

«Первая по sort_order» удалена — молчаливый выбор недопустим.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Section
from app.models.action_journal import Action
from app.models.route import RouteStage
from app.models.work_task import WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService, StockTransaction
from tests.stock.helpers import record_transfer_receive
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route
from tests.test_integrity_invariants import assert_no_invariants_violations


async def _run_to_final_release(
    session: AsyncSession,
    fx: dict,
    qty: Decimal = Decimal("8"),
) -> dict:
    """Довести задание до final_release: issue → receive → complete."""
    task = fx["task"]
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=task.section_id,
        quantity=Decimal("10"),
        task_id=task.id,
        created_by=fx["user"].id,
    )
    task.status = WorkTaskStatus.in_progress
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=task.section_id,
        quantity=qty,
        reason=Reason.COMPLETE,
        task_id=task.id,
        created_by=fx["user"].id,
    ))
    await session.commit()

    from app.services.shopfloor.operations_tasks import final_release
    return await final_release(
        session,
        task_id=task.id,
        quantity=qty,
        actor_id=fx["user"].id,
    )


async def _add_hop_stage(
    session: AsyncSession,
    fx: dict,
    *,
    storage_section_id: int | None,
    stage_kind: str = "transit",
    section_id: int | None = None,
) -> RouteStage:
    """Добавить этап, следующий за финальным (sequence + 1)."""
    final_stage = await session.get(RouteStage, fx["task"].route_stage_id)
    hop = RouteStage(
        route_id=final_stage.route_id,
        sequence=final_stage.sequence + 1,
        section_id=section_id,
        stage_kind=stage_kind,
        storage_section_id=storage_section_id,
        is_final=False,
        requires_acceptance=False,
    )
    session.add(hop)
    await session.commit()
    return hop


async def _last_release_tx(
    session: AsyncSession,
    fx: dict,
) -> StockTransaction:
    tx = (await session.execute(
        select(StockTransaction)
        .where(
            StockTransaction.task_id == fx["task"].id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
        .order_by(StockTransaction.id.desc())
        .limit(1)
    )).scalar_one()
    await assert_no_invariants_violations(session, context="final-release-destination")
    return tx


async def _final_release_action_count(session: AsyncSession, fx: dict) -> int:
    return (await session.execute(
        select(func.count(Action.id)).where(
            Action.ref_id == fx["task"].id,
            Action.action_type == "final_release",
        )
    )).scalar_one()


# ─── каскад ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destination_is_route_transit_hop(session: AsyncSession) -> None:
    """Транзитный хоп после финального этапа приоритетнее дефолта каталога."""
    fx = await _setup_minimal_route(session)
    # Отдельный склад-хоп, НЕ помеченный дефолтом: маршрут приоритетнее.
    hop_fg = Section(
        code=f"{fx['product'].sku}-HOP", name="Хоп выпуска",
        type="finished_stock", is_active=True, sort_order=50,
    )
    session.add(hop_fg)
    await session.commit()
    await _add_hop_stage(session, fx, storage_section_id=hop_fg.id)

    await _run_to_final_release(session, fx)

    tx = await _last_release_tx(session, fx)
    assert tx.to_location_id == hop_fg.id


@pytest.mark.asyncio
async def test_next_stage_production_falls_back_to_default(session: AsyncSession) -> None:
    """Следующий этап — production (хоп не задан) → фолбэк на дефолт каталога."""
    fx = await _setup_minimal_route(session)
    prod2 = Section(
        code=f"{fx['product'].sku}-P2", name="Второй цех",
        type="laser", is_active=True, sort_order=60,
    )
    session.add(prod2)
    await session.commit()
    await _add_hop_stage(
        session, fx, storage_section_id=None,
        stage_kind="production", section_id=prod2.id,
    )

    await _run_to_final_release(session, fx)

    tx = await _last_release_tx(session, fx)
    assert tx.to_location_id == fx["fg"].id


@pytest.mark.asyncio
async def test_fallback_to_catalog_default_without_hop(session: AsyncSession) -> None:
    """Хопа в маршруте нет → дефолт справочника (is_output_default)."""
    fx = await _setup_minimal_route(session)

    await _run_to_final_release(session, fx)

    tx = await _last_release_tx(session, fx)
    assert tx.to_location_id == fx["fg"].id


@pytest.mark.asyncio
async def test_broken_hop_rejected(session: AsyncSession) -> None:
    """Хоп ссылается на секцию, переставшую быть складом → отказ,
    а не молчаливая подмена глобальным дефолтом."""
    fx = await _setup_minimal_route(session)
    await _add_hop_stage(session, fx, storage_section_id=fx["fg"].id)
    # Сломанный каталог: секция хопа больше не склад.
    await session.execute(
        update(Section).where(Section.id == fx["fg"].id).values(type="production")
    )
    await session.commit()

    from app.services.shopfloor.operations_tasks import final_release
    with pytest.raises(ValueError, match="не-складскую секцию"):
        await _run_to_final_release(session, fx)

    tx_count = (await session.execute(
        select(func.count(StockTransaction.id)).where(
            StockTransaction.task_id == fx["task"].id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )).scalar_one()
    assert tx_count == 0
    assert await _final_release_action_count(session, fx) == 0


# ─── отказы ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_destination_rejected(session: AsyncSession) -> None:
    """Ни хопа, ни дефолта → отказ: проводки и Action в журнале нет."""
    fx = await _setup_minimal_route(session)
    fx["fg"].is_output_default = False
    await session.commit()

    from app.services.shopfloor.operations_tasks import final_release
    with pytest.raises(ValueError, match="склад выпуска"):
        await _run_to_final_release(session, fx)

    tx_count = (await session.execute(
        select(func.count(StockTransaction.id)).where(
            StockTransaction.task_id == fx["task"].id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )).scalar_one()
    assert tx_count == 0
    assert await _final_release_action_count(session, fx) == 0


@pytest.mark.asyncio
async def test_ambiguous_default_rejected(session: AsyncSession) -> None:
    """Несколько равнозначных дефолтов → отказ, а не молчаливый выбор."""
    fx = await _setup_minimal_route(session)
    other = Section(
        code=f"{fx['product'].sku}-FG2", name="Второй склад ГП",
        type="finished_stock", is_active=True, sort_order=40,
    )
    session.add(other)
    other.is_output_default = True
    await session.commit()

    from app.services.shopfloor.operations_tasks import final_release
    with pytest.raises(ValueError, match="Неоднозначный склад выпуска"):
        await _run_to_final_release(session, fx)

    tx_count = (await session.execute(
        select(func.count(StockTransaction.id)).where(
            StockTransaction.task_id == fx["task"].id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )).scalar_one()
    assert tx_count == 0
    assert await _final_release_action_count(session, fx) == 0
