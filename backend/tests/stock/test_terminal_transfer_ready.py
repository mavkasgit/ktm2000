"""«Готово к передаче»: обычная передача со склада на терминальный участок (#176).

После #136 секция ``SHIPPED`` («Отправлено») — терминальная: ``StockBalance``
там не материализуется (``StockProjectionManager`` пропускает терминал), но
материал приходит туда ОБЫЧНОЙ передачей («Передать»), а не финальным
выпуском. Складская ветка ready-списка
(``app.transfers.queries._fetch_stock_ready_items``) принимала адресатом
только ``is_stock_section``, поэтому строка «К отгрузке → Отправлено»
пропадала из «Готово к передаче», и материал застревал на ``SHIPMENT``.

Топология участков — из сидов: ``SHIPMENT`` (finished_stock) и ``SHIPPED``
(terminal) в одном ГП «Склад готовой продукции» (``app/seeds/spgs.py``),
шаги 11/12 (``app/seeds/routes.py``). Финальность терминального этапа идёт
не от сидера — тот строит ``SHIPPED`` складской веткой с ``is_final=False``
(``app/seeds/seeders/routes_seeder.py:299-302``), — а от план-импортного
пути: билдер маршрута помечает финальным последний шаг
(``app/services/route_builder.py:418-419``), и импорт плана материализует
его как ``RouteStage(section_id=<терминал>, is_final=True)``
(``app/services/plan_import_service.py:1102-1111``); терминал — последний
шаг, поэтому финальный этап именно он. Поэтому фикс проверяется на обоих
предикатах складской ветки: ``queries.py:814`` (адресат в том же ГП) и
``queries.py:823`` (ленивая задача адресата).

Покрывают:
- ready-строка SHIPMENT → SHIPPED: адресат — терминал, действие — «Передать»
  (``is_final=False``), бюджет = остаток источника;
- ``transfer_send`` на терминал: Transfer + полный след ledger, баланса
  приёмника нет, баланс источника уменьшается, задача адресата создаётся
  лениво;
- после передачи всего бюджета строка исчезает, дубликата нет;
- терминал — сток, а не источник: ready-строк с ``section_code == "SHIPPED"``
  не бывает.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import (
    Reason,
    StockBalance,
    StockCommand,
    StockCommandService,
    StockTransaction,
)
from app.transfers.queries import list_ready_to_transfer
from app.transfers.services import transfer_send
from tests.test_integrity_invariants import assert_no_invariants_violations

SHIPMENT_CODE = "SHIPMENT"
SHIPPED_CODE = "SHIPPED"


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_shipment_to_shipped(
    session: AsyncSession, *, sku: str, qty: Decimal,
) -> dict:
    """``SHIPMENT`` (finished_stock) → ``SHIPPED`` (terminal) с материалом на источнике.

    Материал лежит только на источнике (физический остаток); задача адресата
    НЕ создаётся — её создаёт лениво ``transfer_send``, ровно как на складах.
    """
    user = User(
        username=f"{sku}-op",
        email=f"{sku}@local",
        full_name="Terminal Ready Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    shipment = Section(
        code=SHIPMENT_CODE, name="К отгрузке", type="finished_stock",
        is_active=True, sort_order=100,
    )
    shipped = Section(
        code=SHIPPED_CODE, name="Отправлено", type="terminal",
        is_active=True, sort_order=110,
    )
    session.add_all([shipment, shipped])
    await session.flush()

    # Один ГП на склад ГП, отгрузку и «Отправлено» — как в сиде.
    spg = StorageProductionGroup(
        code=f"{sku}-FG", name="Склад готовой продукции", is_active=True, sort_order=60,
    )
    session.add(spg)
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg.id, section_id=shipment.id, sort_order=0),
        SpgSection(spg_id=spg.id, section_id=shipped.id, sort_order=1),
    ])

    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True,
    )
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    shipment_stage = RouteStage(
        route_id=route.id, sequence=11, section_id=shipment.id, is_final=False,
    )
    shipped_stage = RouteStage(
        route_id=route.id, sequence=12, section_id=shipped.id, is_final=True,
    )
    session.add_all([shipment_stage, shipped_stage])
    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.released,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(position)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    shipment_line = SectionPlanLine(
        internal_plan_id=internal_plan.id, plan_position_id=position.id,
        section_id=shipment.id, product_id=product.id, route_id=route.id,
        route_stage_id=shipment_stage.id, sequence=11, planned_quantity=qty,
    )
    shipped_line = SectionPlanLine(
        internal_plan_id=internal_plan.id, plan_position_id=position.id,
        section_id=shipped.id, product_id=product.id, route_id=route.id,
        route_stage_id=shipped_stage.id, sequence=12, planned_quantity=qty,
    )
    session.add_all([shipment_line, shipped_line])
    await session.flush()

    task = WorkTask(
        section_plan_line_id=shipment_line.id, section_id=shipment.id,
        product_id=product.id, route_stage_id=shipment_stage.id,
        planned_quantity=qty, status=WorkTaskStatus.ready,
    )
    session.add(task)
    await session.flush()

    # Физический остаток источника — каноническим путём (ledger + проекция).
    await StockCommandService().record(session, StockCommand(
        product_id=product.id,
        to_location_id=shipment.id,
        quantity=qty,
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.flush()

    return {
        "user": user,
        "product": product,
        "shipment": shipment,
        "shipped": shipped,
        "shipment_line": shipment_line,
        "shipped_line": shipped_line,
        "task": task,
    }


async def _ready_items(
    session: AsyncSession, *, section_id: int | None = None,
) -> list[dict]:
    """Строки «Готово к передаче» — публичный read-path ready-страницы."""
    result = await list_ready_to_transfer(session, section_id=section_id)
    return result["items"]


async def _balance(session: AsyncSession, product_id: int, location_id: int) -> Decimal:
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
        )
    )
    bal = row.scalars().one_or_none()
    return bal.balance_qty if bal else Decimal("0")


# ─── ready-строка в терминал ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_row_offers_ordinary_transfer_into_terminal(
    session: AsyncSession,
) -> None:
    """SHIPMENT → SHIPPED виден в «Готово к передаче» как обычная передача.

    Пин: ``backend/app/transfers/queries.py:811`` — адресат допущен, потому что
    ``destination_accepts_transfer`` включает ``is_terminal_section``; далее
    ``queries.py:814`` (адресат в том же ГП) и ``queries.py:823`` (задача
    адресата ещё не создана — ленивая) строку больше не скрывают. До #176
    оба предиката знали только ``is_stock_section`` — строки не было.
    """
    fx = await _make_shipment_to_shipped(session, sku="T176R", qty=Decimal("12"))

    items = await _ready_items(session, section_id=fx["shipment"].id)
    rows = [item for item in items if item["task_id"] == fx["task"].id]
    assert len(rows) == 1, f"ожидал одну ready-строку SHIPMENT → SHIPPED, получил: {items}"

    row = rows[0]
    assert row["section_code"] == SHIPMENT_CODE
    assert row["next_section_code"] == SHIPPED_CODE
    assert row["next_section_name"] == "Отправлено"
    # Этап адресата финальный (последний шаг маршрута), но действие строки —
    # «Передать»: UI выбирает передачу/выпуск по ``is_final``
    # (frontend TransfersPage.tsx:415).
    assert row["next_step_is_final"] is True
    assert row["is_final"] is False
    # Бюджет строки = min(план-остаток, физический остаток) источника.
    assert Decimal(row["transferable_quantity"]) == Decimal("12")


# ─── обычная передача в терминал ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ordinary_transfer_into_terminal_keeps_ledger_without_balance(
    session: AsyncSession,
) -> None:
    """``transfer_send`` на терминал: Transfer, полный след ledger, баланса приёмника нет.

    Пин: ``backend/app/transfers/services.py:256`` (задача адресата создаётся
    лениво), ``services.py:321`` (``Transfer.to_section_id`` = терминал),
    ``services.py:383`` (TRANSFER_SEND from=SHIPMENT → to=SHIPPED) и
    ``services.py:415`` (TRANSFER_RECEIVE); проекция остатков пропускает
    терминал — ``backend/app/stock/services.py:198,204``.
    """
    fx = await _make_shipment_to_shipped(session, sku="T176S", qty=Decimal("12"))

    result = await transfer_send(
        session,
        from_task_id=fx["task"].id,
        quantity=Decimal("4"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    transfer = (await session.execute(select(Transfer))).scalars().one()
    assert transfer.id == result["transfer_id"]
    assert transfer.to_section_id == fx["shipped"].id

    txs = (await session.execute(
        select(StockTransaction).order_by(StockTransaction.id)
    )).scalars().all()
    assert [tx.reason for tx in txs] == [
        Reason.MANUAL_IN, Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE,
    ]
    send_tx = txs[1]
    assert (send_tx.from_location_id, send_tx.to_location_id) == (
        fx["shipment"].id, fx["shipped"].id,
    )

    # Терминал — не склад: строки баланса приёмника не появляется…
    assert (await session.execute(
        select(StockBalance).where(StockBalance.location_id == fx["shipped"].id)
    )).scalar_one_or_none() is None
    # …а остаток источника уменьшился ровно на переданное.
    assert await _balance(session, fx["product"].id, fx["shipment"].id) == Decimal("8")

    # Задача на терминале создана лениво — как для складского адресата.
    to_task = await session.get(WorkTask, transfer.to_task_id)
    assert to_task is not None
    assert to_task.section_plan_line_id == fx["shipped_line"].id
    assert to_task.section_id == fx["shipped"].id

    await assert_no_invariants_violations(session, context="terminal-ready-transfer")


# ─── бюджет исчерпан ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_row_disappears_after_full_transfer(session: AsyncSession) -> None:
    """После передачи всего бюджета строка SHIPMENT → SHIPPED исчезает, дубликата нет.

    Пин: ``backend/app/transfers/queries.py:872`` — ``if transferable <= 0:
    continue``; бюджет читается из ledger тем же модулем, что и write-guard
    (``backend/app/transfers/transferable.py::compute_stock_section_transferable``).
    Передаём ровно ``transferable_quantity`` из строки: read- и write-бюджет
    обязаны совпадать, иначе ``transfer_send`` отклонил бы подачу.
    """
    fx = await _make_shipment_to_shipped(session, sku="T176F", qty=Decimal("12"))

    items = await _ready_items(session, section_id=fx["shipment"].id)
    rows = [item for item in items if item["task_id"] == fx["task"].id]
    assert len(rows) == 1, f"строка должна быть до передачи, получил: {items}"

    await transfer_send(
        session,
        from_task_id=fx["task"].id,
        quantity=Decimal(rows[0]["transferable_quantity"]),
        actor_id=fx["user"].id,
    )
    await session.commit()

    items = await _ready_items(session, section_id=fx["shipment"].id)
    assert [item for item in items if item["task_id"] == fx["task"].id] == []
    assert [item for item in items if item["next_section_code"] == SHIPPED_CODE] == []

    await assert_no_invariants_violations(session, context="terminal-ready-transfer")


# ─── терминал — не источник ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_section_is_never_a_ready_source(session: AsyncSession) -> None:
    """Материал на терминале не делает его источником ready-строки.

    Пин: ``backend/app/transfers/queries.py:754`` — складская ветка обходит
    только ``is_stock_section``-секции; ``queries.py:517`` — производственная
    ветка только секции типа ``production``. Терминал не проходит ни одну,
    хотя принимает передачу, а его задача живая и этап финальный.
    """
    fx = await _make_shipment_to_shipped(session, sku="T176T", qty=Decimal("12"))
    await transfer_send(
        session,
        from_task_id=fx["task"].id,
        quantity=Decimal("4"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    # Контроль: принимающая задача на терминале действительно появилась…
    to_task = (await session.execute(
        select(WorkTask).where(WorkTask.section_id == fx["shipped"].id)
    )).scalars().one()
    assert to_task.section_plan_line_id == fx["shipped_line"].id

    # …но источником ready-строки терминал не становится, и складская строка жива.
    items = await _ready_items(session)
    assert [item for item in items if item["section_code"] == SHIPPED_CODE] == []
    assert [item for item in items if item["task_id"] == fx["task"].id], (
        f"контроль: складская строка SHIPMENT → SHIPPED должна остаться: {items}"
    )

    await assert_no_invariants_violations(session, context="terminal-ready-transfer")
