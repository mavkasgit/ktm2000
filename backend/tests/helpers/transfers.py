"""Общие тест-фабрики transfers-домена — канонические определения (#131 follow-up).

Перенесены дословно из трёх тест-модулей без изменения поведения:

- ``tests.stock.test_transfer_stage2`` — ``_make_two_ghp_setup``,
  ``_make_tasks_transferable``;
- ``tests.test_transfer_dimensions`` — ``_make_dim_route_fixture``,
  ``_seed_balance``, ``_make_transform_route_fixture``,
  ``_tasks_for_position``, ``_complete_saw``;
- ``tests.test_transfer_budget_consistency`` — ``_ready_row`` (+ сантинел
  ``_UNSET``, использовавшийся только ею).

Модули-источники реэкспортируют имена отсюда, поэтому старые пути импорта
(``from tests.stock.test_transfer_stage2 import _make_two_ghp_setup`` и
проч.) продолжают работать — определения живут в одном месте.

Версии этих имён в ДРУГИХ доменах сюда НЕ переносились: например,
``_seed_balance`` в ``test_product_wip_stats_dimensions.py`` имеет свою
сигнатуру и остаётся локальным для своего модуля.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from app.models import Product, ProductType, Section, User
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.work_task import WorkTask
from app.services.material_operations import completed_operations_for_task
from app.stock.models import Reason
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    _release_via_take_to_work,
    assert_no_invariants_violations,
)

__all__ = [
    "_UNSET",
    "_complete_saw",
    "_make_dim_route_fixture",
    "_make_tasks_transferable",
    "_make_transform_route_fixture",
    "_make_two_ghp_setup",
    "_ready_row",
    "_seed_balance",
    "_tasks_for_position",
]


# ─── Из tests/stock/test_transfer_stage2.py ─────────────────────────────────


async def _make_two_ghp_setup(
    session: AsyncSession,
    *,
    sku: str = "STG2",
    qty: Decimal = Decimal(10),
) -> dict:
    """Две production-секции в разных GHP с маршрутом из двух этапов.

    Возвращает user, product, from_task, to_task, sections, transfer_id=None.
    """
    user = await _make_user(session, f"{sku}@local")

    sec1 = Section(code=f"{sku}-S1", name="S1", type="production", is_active=True, sort_order=0)
    sec2 = Section(code=f"{sku}-S2", name="S2", type="production", is_active=True, sort_order=1)
    session.add_all([sec1, sec2])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
    session.add_all([spg_a, spg_b])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec1.id, sort_order=0),
        SpgSection(spg_id=spg_b.id, section_id=sec2.id, sort_order=0),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(sec1, "OP1"), (sec2, "OP2")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=datetime(2026, 5, 1), period_end=datetime(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()
    await session.commit()

    return {
        "user": user,
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [sec1, sec2],
        "route": route,
    }


async def _make_tasks_transferable(
    session: AsyncSession,
    client,
    setup: dict,
) -> dict:
    """Take-to-work → issue → complete on source task.

    Returns {from_task_id, to_task_id, user}.
    """
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id)
    )).scalars().all()
    assert len(tasks) >= 2
    src = tasks[0]
    dst = tasks[1]

    # Create a stock section for transfer_receive seed
    stock = Section(code="T2-STK", name="Stock", type="raw_stock",
                    is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()
    stock_id = stock.id
    # ADR-0043/0055: приход на складской участок — это материал ДО первого
    # этапа маршрута, но ровно с тем же признаком, который выведет
    # plan-driven списание TRANSFER_RECEIVE ниже. Без этого приход лёг бы в
    # NULL-группу, а списание искало бы группу маршрута и получало «available 0».
    stock_ops = await completed_operations_for_task(session, src)

    svc = StockCommandService()
    # Seed stock balance
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=None,
        to_location_id=stock_id,
        quantity=src.planned_quantity,
        reason=Reason.MANUAL_IN,
        completed_operations=stock_ops,
        created_by=setup["user"].id,
    ))
    # TRANSFER_RECEIVE: material received on source section (issued)
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=stock_id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.TRANSFER_RECEIVE,
        task_id=src.id,
        created_by=setup["user"].id,
    ))
    # Завершение фикстуры: событие выпуска без движения баланса. Материал
    # уже лежит на участке в группе СВОЕГО этапа (его положил
    # TRANSFER_RECEIVE выше с task_id=src), поэтому именно эту проводку
    # прочитает transfer_send задания-источника (ADR-0055).
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=src.section_id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.COMPLETE,
        task_id=src.id,
        source_ref="test_seed",
        created_by=setup["user"].id,
    ))
    await session.flush()

    # Verify source is transferable (check via ledger)
    from app.stock.services import StockProjectionManager
    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, src.id)
    assert cache["completed_quantity"] >= Decimal(0)

    return {"from_task_id": src.id, "to_task_id": dst.id, "user": setup["user"]}


# ─── Из tests/test_transfer_dimensions.py ───────────────────────────────────


async def _make_dim_route_fixture(
    session: AsyncSession,
    *,
    sku: str,
    qty: Decimal,
    length_mm: float | None = None,
) -> dict:
    """raw_stock(SPG A) → prod1(SPG B) → prod2(SPG C, final).

    Все секции в разных ГХП: stock→prod1 и prod1→prod2 — кросс-ГХП передачи,
    обе видны в ready-списке. Позиция несёт ``input_dimensions`` (длину).
    """
    raw = Section(code=f"{sku}-RAW", name="RAW", type="raw_stock", is_active=True, sort_order=0)
    prod1 = Section(code=f"{sku}-P1", name="P1", type="production", is_active=True, sort_order=1)
    prod2 = Section(code=f"{sku}-P2", name="P2", type="production", is_active=True, sort_order=2)
    # Адресат FINAL_RELEASE: без секции ГП финальный выпуск отклоняется.
    fg = Section(code=f"{sku}-FG", name="Склад ГП", type="finished_stock", is_active=True, sort_order=90,
             is_output_default=True)  # адресат FINAL_RELEASE по умолчанию (#137)
    session.add_all([raw, prod1, prod2, fg])
    await session.flush()

    spgs: list[StorageProductionGroup] = []
    for idx, (sec, code) in enumerate(
        [(raw, f"{sku}-A"), (prod1, f"{sku}-B"), (prod2, f"{sku}-C")]
    ):
        spg = StorageProductionGroup(code=code, name=code, is_active=True, sort_order=idx)
        session.add(spg)
        await session.flush()
        session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=0))
        spgs.append(spg)

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate(
        [(raw, "ISSUE_RAW"), (prod1, "P1_OP"), (prod2, "P2_OP")], start=1
    ):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 3))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}",
        name="p",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=qty,
        input_dimensions={"length_mm": int(length_mm)} if length_mm is not None else None,
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
        route_assigned_at=None,
    )
    session.add(pos)
    await session.commit()
    return {
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [raw, prod1, prod2],
        "spgs": spgs,
    }


async def _section_route_operations(
    session: AsyncSession, section_id: int
) -> list[str] | None:
    """Признак материала, лежащего на секции — операции её этапа маршрута.

    Тот же резолвер, что и у ``record()``: ``SectionOperation`` всех этапов
    маршрута с ``sequence <=`` этапа этой секции. Нужен сидам, которые
    заполняют склад ДО появления заданий (take-to-work ещё не вызван),
    поэтому маршрут берётся по самой секции, а не по заданию.

    ``None`` — секция вне маршрута: признак неизвестен, группа ``NULL``.
    """
    from app.services.material_operations import completed_operations_through_stage

    stage = await session.scalar(
        select(RouteStage)
        .where(RouteStage.section_id == section_id)
        .order_by(RouteStage.id)
        .limit(1)
    )
    if stage is None:
        return None
    return await completed_operations_through_stage(
        session, route_id=stage.route_id, through_sequence=stage.sequence
    )


async def _seed_balance(
    session: AsyncSession,
    *,
    user_id: int,
    location_id: int,
    product_id: int,
    qty: Decimal,
    dimensions: dict | None = None,
    ops: list[str] | None = None,
) -> None:
    """Приход остатка на складскую секцию в ops-группе её этапа маршрута.

    ADR-0055: списание точное. Позже этот остаток списывает план-driven
    ``TRANSFER_SEND``, а ``record()`` выводит его признак из маршрута
    задания. Наивный ``MANUAL_IN`` без признака лёг бы в ``NULL``-группу,
    и списание получало бы «available 0». Поэтому здесь берётся тот же
    источник: операции секции до её собственного этапа маршрута.

    ``ops`` передаётся явно там, где нужна не своя группа секции (например
    приход на «Склад подготовки», который спишет задание другого этапа).
    Секция вне маршрута остаётся в ``NULL``-группе — там признак неизвестен.
    """
    if ops is None:
        ops = await _section_route_operations(session, location_id)
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            dimensions=dimensions,
            completed_operations=ops,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _make_transform_route_fixture(
    session: AsyncSession,
    *,
    sku: str,
    qty: Decimal,
    input_quantity: Decimal | None,
    input_dimensions: dict | None,
    outputs: list[dict],
    final_transform: bool = False,
    separate_ghps: bool = False,
) -> dict:
    """raw → saw(transforms) → pack(final, если не final_transform).

    ``saw`` помечен ``transforms_dimensions=True``; позиция несёт вход и
    выходы. Для D2-тестов saw не финальный (дальше pack); для D3 — saw
    сам финальный этап. Секция ``fg`` (finished_stock) — приёмник
    финального выпуска. ``separate_ghps`` — saw/pack в разных ГХП
    (для авто-передачи по выходам, тикет #91).
    """
    raw = Section(code=f"{sku}-RAW", name="RAW", type="raw_stock", is_active=True, sort_order=0)
    saw = Section(code=f"{sku}-SAW", name="SAW", type="production", is_active=True, sort_order=1)
    pack = Section(code=f"{sku}-PACK", name="PACK", type="production", is_active=True, sort_order=2)
    fg = Section(code=f"{sku}-FG", name="FG", type="finished_stock", is_active=True, sort_order=3,
             is_output_default=True)  # адресат FINAL_RELEASE по умолчанию (#137)
    session.add_all([raw, saw, pack, fg])
    await session.flush()

    if separate_ghps:
        spg_saw = StorageProductionGroup(code=f"{sku}-GHPSAW", name="GHP-SAW", is_active=True, sort_order=0)
        spg_pack = StorageProductionGroup(code=f"{sku}-GHPPACK", name="GHP-PACK", is_active=True, sort_order=1)
        session.add_all([spg_saw, spg_pack])
        await session.flush()
        for sec, spg in ((raw, spg_saw), (saw, spg_saw), (pack, spg_pack), (fg, spg_pack)):
            session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=0))
        await session.flush()
    else:
        spg = StorageProductionGroup(code=f"{sku}-GHP", name="GHP", is_active=True, sort_order=0)
        session.add(spg)
        await session.flush()
        for sec in (raw, saw, pack, fg):
            session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=0))
        await session.flush()

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage_defs = [
        (raw, "ISSUE_RAW", 1, False),
        (saw, "SAW", 2, final_transform),
    ]
    if not final_transform:
        stage_defs.append((pack, "PACK", 3, True))
    for sec, code, seq, is_final in stage_defs:
        st = RouteStage(
            route_id=route.id,
            sequence=seq,
            section_id=sec.id,
            is_final=is_final,
            transforms_dimensions=(code == "SAW"),
        )
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    await session.flush()

    plan = ProductionPlan(
        plan_no=f"P-{sku}",
        name="p",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=qty,
        input_quantity=input_quantity,
        input_dimensions=input_dimensions,
        outputs=outputs,
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
        route_assigned_at=None,
    )
    session.add(pos)
    await session.commit()
    return {"product": product, "plan": plan, "position": pos, "sections": [raw, saw, pack, fg]}


async def _tasks_for_position(session: AsyncSession, position_id: int) -> Sequence[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()


async def _complete_saw(session: AsyncSession, *, saw_task: WorkTask, user: User) -> None:
    """Завести вход 100 × 2700 на пилу и полностью её раскроить (100 → 900+1800).

    ADR-0055: списание точное. Трансформ на пиле списывает материал,
    который на секцию пришёл с ПРЕДЫДУЩЕГО этапа и потому лежит в
    ops-группе «до своего этапа» — ровно ту, которую выведет
    ``TRANSFORM_CONSUME``. Наивный ``MANUAL_IN`` без признака лёг бы в
    ``NULL``-группу, и раскрой падал бы с «введено 100, доступно 0».
    """
    from app.services.material_operations import previous_stage_sequence
    from app.services.shopfloor.operations_tasks import complete_task

    previous_sequence = await previous_stage_sequence(session, saw_task)
    consume_ops = await completed_operations_for_task(
        session, saw_task,
        through_sequence=previous_sequence if previous_sequence is not None else 0,
    )
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=saw_task.product_id,
            from_location_id=None,
            to_location_id=saw_task.section_id,
            quantity=Decimal(100),
            reason=Reason.MANUAL_IN,
            dimensions={"length_mm": 2700},
            completed_operations=consume_ops,
            created_by=user.id,
        ),
    )
    await session.commit()
    await complete_task(
        session,
        task_id=saw_task.id,
        good_quantity=Decimal(100),
        defect_quantity=Decimal(0),
        actor_id=user.id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="complete-saw")


# ─── Из tests/test_transfer_budget_consistency.py ───────────────────────────

_UNSET = object()


async def _ready_row(
    client,
    user: User,
    section_id: int,
    *,
    task_id: int | None = None,
    dims: object = _UNSET,
) -> dict:
    """Ровно одна ready-строка ``/api/transfers/ready`` по (задача, размер).

    ``dims=_UNSET`` — без фильтра по габариту; ``dims=None`` — искать
    безразмерную строку (габарит равен NULL).
    """
    resp = await client.get(
        f"/api/transfers/ready?section_id={section_id}", headers=_auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    matches = [
        item
        for item in items
        if (task_id is None or item["task_id"] == task_id)
        and (dims is _UNSET or item.get("dimensions") == dims)
    ]
    assert len(matches) == 1, f"ожидал ровно одну ready-строку, получил: {items}"
    return matches[0]
