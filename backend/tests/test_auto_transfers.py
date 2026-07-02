"""Tests for auto-transfer creation after prepare/complete.

These tests build a multi-section route via
``_make_six_section_fixture`` (reused pattern from
``test_transfers_module.py``) and verify that ``complete_task`` and
``prepare_section_task`` create cross-GHP Transfer rows automatically.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.movement import Movement, MovementType
from app.services.shopfloor.cache import _refresh_task_cache


async def _make_user(session, email: str = "auto@local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Auto Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _make_two_ghp_fixture(session, *, sku: str, qty: Decimal) -> dict:
    """Две секции в РАЗНЫХ ГХП: production_1 → production_2.

    Минимально, чтобы cross-GHP перемещение было возможно.
    """
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
        ProductionPlan,
        ProductionPlanStatus,
    )

    sec1 = Section(code=f"{sku}-S1", name="S1", kind="production", is_active=True, sort_order=0)
    sec2 = Section(code=f"{sku}-S2", name="S2", kind="production", is_active=True, sort_order=1)
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

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(sec1, "OP1"), (sec2, "OP2")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=__import__("datetime").date(2026, 5, 1),
        period_end=__import__("datetime").date(2026, 5, 31),
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
    await session.commit()
    return {"product": product, "plan": plan, "position": pos, "sections": [sec1, sec2], "spgs": [spg_a, spg_b]}


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post("/api/production-planning/rows/take-to-work", json={"position_ids": [position_id]})
    assert resp.status_code == 200, resp.text


async def _issue_first_task(session, user, task_id, qty: Decimal, idempotency_key: str | None = None) -> None:
    task = await session.get(WorkTask, task_id)
    m = Movement(
        product_id=task.product_id, task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id, to_section_id=task.section_id,
        movement_type=MovementType.issue_to_work, quantity=qty, created_by=user.id,
    )
    session.add(m)
    await session.flush()
    await _refresh_task_cache(session, task_id)
    from app.services.shopfloor.cache import _refresh_section_plan_line_cache
    await _refresh_section_plan_line_cache(session, task.section_plan_line_id)
    await session.flush()


async def _complete_first_task(
    session,
    user,
    client,
    task_id: int,
    qty: Decimal,
    idempotency_key: str | None = None,
    auto_transfer_next: bool = False,
) -> None:
    issue_key = f"{idempotency_key}:issue" if idempotency_key else None
    await _issue_first_task(session, user, task_id, qty, idempotency_key=issue_key)
    body = {
        "good_quantity": str(qty),
        "defect_quantity": "0",
        "shortage_strategy": "negative_remainder",
    }
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    if auto_transfer_next:
        body["auto_transfer_next"] = True
    resp = await client.post(f"/api/shopfloor/tasks/{task_id}/complete", json=body)
    assert resp.status_code == 200, resp.text


async def test_auto_create_transfer_creates_cross_ghp(client, session) -> None:
    """Helper ``auto_create_transfer_after_complete`` must create a Transfer
    pointing from task on section 1 to task on section 2 (different GHPs)."""
    from app.transfers.services import auto_create_transfer_after_complete

    user = await _make_user(session)
    fx = await _make_two_ghp_fixture(session, sku="AUTO-1", qty=Decimal("5"))
    await _release_via_take_to_work(client, fx["position"].id)

    # Найти задачи, созданные take-to-work
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    assert len(tasks) == 2
    task1, task2 = tasks[0], tasks[1]
    assert task1.section_id == fx["sections"][0].id
    assert task2.section_id == fx["sections"][1].id

    # Прямой вызов библиотечного хелпера (после revert complete_task
    # больше не интегрирован с auto-transfer, тестируем сам хелпер).
    result = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=Decimal("5"),
        actor_id=user.id, idempotency_key="k-direct",
    )
    assert result is not None
    assert result.get("idempotent_replay") is not True

    # Должен появиться ровно один Transfer cross-GHP
    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 1
    t = transfers[0]
    assert t.from_task_id == task1.id
    assert t.to_task_id == task2.id
    assert t.from_section_id == fx["sections"][0].id
    assert t.to_section_id == fx["sections"][1].id
    assert t.is_post_factum is True
    # Under the new explicit-transfer model, transfer_send auto-accepts:
    # the transfer is immediately marked ``accepted`` and the destination
    # task transitions to ``ready``.
    assert t.status == TransferStatus.accepted


async def test_complete_no_transfer_within_same_ghp(client, session) -> None:
    """Когда секции в ОДНОЙ ГХП, transfer_send не должен вызываться."""
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition, PlanPositionStatus, PlanPositionValidationStatus,
        PlanSourceType, ProductionPlan, ProductionPlanStatus,
    )
    from datetime import date

    user = await _make_user(session)
    sec1 = Section(code="SAM-1", name="S1", kind="production", is_active=True, sort_order=0)
    sec2 = Section(code="SAM-2", name="S2", kind="production", is_active=True, sort_order=1)
    session.add_all([sec1, sec2])
    await session.flush()
    spg = StorageProductionGroup(code="SAM-SPG", name="One", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg.id, section_id=sec1.id, sort_order=0),
        SpgSection(spg_id=spg.id, section_id=sec2.id, sort_order=0),
    ])
    product = Product(sku="SAM", name="SAM", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    route = ProductionRoute(name="r", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate([(sec1, "A"), (sec2, "B")], start=1):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 2))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))
    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))
    plan = ProductionPlan(plan_no="P-SAM", name="p", status=ProductionPlanStatus.approved,
                          period_start=date(2026, 5, 1), period_end=date(2026, 5, 31))
    session.add(plan)
    await session.flush()
    pos = PlanPosition(production_plan_id=plan.id, product_id=product.id,
                       source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
                       quantity=Decimal("3"), source_payload={}, status=PlanPositionStatus.approved,
                       validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
                       period_start=plan.period_start, period_end=plan.period_end,
                       has_pack_ops=False, route_id=route.id, route_assigned_at=None)
    session.add(pos)
    await session.commit()

    await _release_via_take_to_work(client, pos.id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    await _complete_first_task(session, user, client, tasks[0].id, Decimal("3"), idempotency_key="k-same")

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert transfers == [], "Внутри одной ГХП перемещение создаваться не должно"


async def test_complete_no_transfer_on_final_stage(client, session) -> None:
    """Финальный шаг маршрута — перемещать некуда, Transfer не создаётся."""
    from datetime import date
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition, PlanPositionStatus, PlanPositionValidationStatus,
        PlanSourceType, ProductionPlan, ProductionPlanStatus,
    )

    user = await _make_user(session)
    sec = Section(code="FIN-1", name="F", kind="production", is_active=True, sort_order=0)
    session.add(sec)
    await session.flush()
    spg = StorageProductionGroup(code="FIN-SPG", name="F", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=0))
    product = Product(sku="FIN", name="F", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    route = ProductionRoute(name="r-fin", is_active=True)
    session.add(route)
    await session.flush()
    st = RouteStage(route_id=route.id, sequence=1, section_id=sec.id, is_final=True)
    session.add(st)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code="X", operation_name="X"))
    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))
    plan = ProductionPlan(plan_no="P-FIN", name="p", status=ProductionPlanStatus.approved,
                          period_start=date(2026, 5, 1), period_end=date(2026, 5, 31))
    session.add(plan)
    await session.flush()
    pos = PlanPosition(production_plan_id=plan.id, product_id=product.id,
                       source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
                       quantity=Decimal("2"), source_payload={}, status=PlanPositionStatus.approved,
                       validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
                       period_start=plan.period_start, period_end=plan.period_end,
                       has_pack_ops=False, route_id=route.id, route_assigned_at=None)
    session.add(pos)
    await session.commit()

    await _release_via_take_to_work(client, pos.id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    await _complete_first_task(session, user, client, tasks[0].id, Decimal("2"), idempotency_key="k-fin")

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert transfers == [], "На финальном шаге перемещение не должно создаваться"


async def test_auto_create_transfer_is_idempotent(client, session) -> None:
    """Повторный вызов хелпера с тем же idempotency_key не должен дублировать Transfer."""
    from app.transfers.services import auto_create_transfer_after_complete

    user = await _make_user(session)
    fx = await _make_two_ghp_fixture(session, sku="IDEM", qty=Decimal("4"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    assert len(tasks) == 2
    task1, task2 = tasks[0], tasks[1]

    # Первый вызов хелпера — должен создать Transfer
    first = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=Decimal("4"),
        actor_id=user.id, idempotency_key="k-idem-1",
    )
    assert first is not None
    assert first.get("idempotent_replay") is not True

    # Повторный вызов с тем же idempotency_key — должен вернуть idempotent_replay
    # и НЕ создать дубль (симулирует сетевой ретрай).
    second = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=Decimal("4"),
        actor_id=user.id, idempotency_key="k-idem-1",
    )
    assert second is not None
    assert second.get("idempotent_replay") is True, "Повторный вызов должен вернуть idempotent_replay"

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 1, f"Ожидался 1 Transfer, получили {len(transfers)}"
    assert transfers[0].from_task_id == task1.id
    assert transfers[0].to_task_id == task2.id


async def test_complete_with_auto_transfer_next_true_creates_transfer(client, session) -> None:
    """Флаг auto_transfer_next=true в payload complete_task создаёт Transfer автоматически."""
    user = await _make_user(session)
    fx = await _make_two_ghp_fixture(session, sku="FLAG-ON", qty=Decimal("3"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    task1 = tasks[0]

    await _complete_first_task(session, user, client, task1.id, Decimal("3"), idempotency_key="k-flag-on", auto_transfer_next=True)

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 1
    assert transfers[0].from_task_id == task1.id
    assert transfers[0].to_task_id == tasks[1].id
    assert transfers[0].is_post_factum is True


async def test_complete_with_auto_transfer_next_false_no_transfer(client, session) -> None:
    """Флаг auto_transfer_next=false (default) — Transfer НЕ создаётся (старое поведение)."""
    user = await _make_user(session)
    fx = await _make_two_ghp_fixture(session, sku="FLAG-OFF", qty=Decimal("3"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id.asc()))).scalars().all()
    task1 = tasks[0]

    await _complete_first_task(session, user, client, task1.id, Decimal("3"), idempotency_key="k-flag-off", auto_transfer_next=False)

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert transfers == [], "Без флага auto_transfer_next перемещение создаваться не должно"


async def _make_transit_fixture(session, *, sku: str, qty: Decimal) -> dict:
    """Три секции: production_1 → transit(WIP stock) → production_2.

    production_1 и production_2 в РАЗНЫХ ГХП, transit — в ТРЕТЬЕЙ ГХП.
    Transit-stage: section_id=None, storage_section_id=<storage_section.id>.
    plan_generation создаёт SectionPlanLine для transit, но WorkTask — нет.

    Создаёт SectionPlanLine и WorkTask напрямую (минуя take-to-work,
    который пока не поддерживает transit-стадии в маршруте).
    """
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
        ProductionPlan,
        ProductionPlanStatus,
    )
    from app.models.internal_plan import InternalPlan, SectionPlanLine
    from datetime import date

    sec_prod1 = Section(code=f"{sku}-P1", name="Prod1", kind="production", is_active=True, sort_order=0)
    sec_transit = Section(code=f"{sku}-TR", name="Transit", kind="wip_stock", is_active=True, sort_order=1)
    sec_prod2 = Section(code=f"{sku}-P2", name="Prod2", kind="production", is_active=True, sort_order=2)
    session.add_all([sec_prod1, sec_transit, sec_prod2])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
    spg_c = StorageProductionGroup(code=f"{sku}-C", name="C", is_active=True, sort_order=2)
    session.add_all([spg_a, spg_b, spg_c])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec_prod1.id, sort_order=0),
        SpgSection(spg_id=spg_b.id, section_id=sec_transit.id, sort_order=0),
        SpgSection(spg_id=spg_c.id, section_id=sec_prod2.id, sort_order=0),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    # Stage 1: production_1
    st1 = RouteStage(
        route_id=route.id, sequence=1, section_id=sec_prod1.id,
        is_final=False, stage_kind="production",
    )
    session.add(st1)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st1.id, sequence=1, operation_code="OP1", operation_name="OP1"))

    # Stage 2: transit (section_id=None, storage_section_id=sec_transit.id)
    st_transit = RouteStage(
        route_id=route.id, sequence=2, section_id=None,
        storage_section_id=sec_transit.id,
        is_final=False, stage_kind="transit",
    )
    session.add(st_transit)
    await session.flush()

    # Stage 3: production_2
    st2 = RouteStage(
        route_id=route.id, sequence=3, section_id=sec_prod2.id,
        is_final=True, stage_kind="production",
    )
    session.add(st2)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st2.id, sequence=1, operation_code="OP2", operation_name="OP2"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
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

    # Создаём InternalPlan + SectionPlanLine + WorkTask напрямую,
    # чтобы не проходить через take-to-work (тот пока не умеет transit).
    ip = InternalPlan(production_plan_id=plan.id, release_batch_id=None)
    session.add(ip)
    await session.flush()

    # line_seq 1: production_1 — секция prod1
    line1 = SectionPlanLine(
        internal_plan_id=ip.id, plan_position_id=pos.id,
        section_id=sec_prod1.id, product_id=product.id,
        route_id=route.id, route_stage_id=st1.id,
        sequence=1, planned_quantity=qty,
    )
    session.add(line1)
    await session.flush()

    # line_seq 2: transit — секция wip_stock (transit)
    line_transit = SectionPlanLine(
        internal_plan_id=ip.id, plan_position_id=pos.id,
        section_id=sec_transit.id, product_id=product.id,
        route_id=route.id, route_stage_id=st_transit.id,
        sequence=2, planned_quantity=qty,
    )
    session.add(line_transit)
    await session.flush()

    # line_seq 3: production_2 — секция prod2
    line3 = SectionPlanLine(
        internal_plan_id=ip.id, plan_position_id=pos.id,
        section_id=sec_prod2.id, product_id=product.id,
        route_id=route.id, route_stage_id=st2.id,
        sequence=3, planned_quantity=qty,
    )
    session.add(line3)
    await session.flush()

    # WorkTask только для production-этапов (transit пропускается)
    task1 = WorkTask(
        section_plan_line_id=line1.id, section_id=sec_prod1.id,
        product_id=product.id, route_stage_id=st1.id,
        planned_quantity=qty, status=WorkTaskStatus.ready,
    )
    session.add(task1)
    await session.flush()

    task2 = WorkTask(
        section_plan_line_id=line3.id, section_id=sec_prod2.id,
        product_id=product.id, route_stage_id=st2.id,
        planned_quantity=qty, status=WorkTaskStatus.waiting_previous,
    )
    session.add(task2)
    await session.flush()

    await session.commit()
    return {
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [sec_prod1, sec_transit, sec_prod2],
        "spgs": [spg_a, spg_b, spg_c],
        "stages": [st1, st_transit, st2],
        "tasks": [task1, task2],
        "lines": [line1, line_transit, line3],
    }


async def test_auto_transfer_chain_through_single_transit(client, session) -> None:
    """При завершении production_1 в маршруте production_1→transit→production_2
    должны создаться ДВЕ передачи: production_1→transit И transit→production_2.
    Обе передачи — post_factum и accepted."""
    from app.transfers.services import auto_create_transfer_after_complete
    from app.models.internal_plan import SectionPlanLine

    user = await _make_user(session)
    fx = await _make_transit_fixture(session, sku="CHAIN-1", qty=Decimal("10"))

    task1 = fx["tasks"][0]  # production_1 (ready)
    task2 = fx["tasks"][1]  # production_2 (waiting_previous)

    # Прямой вызов хелпера — должен создать цепочку из 2 передач
    result = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=Decimal("10"),
        actor_id=user.id, idempotency_key="k-chain-1",
    )
    assert result is not None

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 2, f"Ожидалось 2 Transfer (chain через transit), получили {len(transfers)}"

    # Первая передача: production_1 → transit (wip_stock)
    t1 = transfers[0]
    assert t1.from_task_id == task1.id
    assert t1.from_section_id == fx["sections"][0].id
    assert t1.to_section_id == fx["sections"][1].id
    assert t1.is_post_factum is True
    assert t1.status == TransferStatus.accepted

    # Вторая передача: transit (wip_stock) → production_2
    t2 = transfers[1]
    assert t2.to_task_id == task2.id
    assert t2.from_section_id == fx["sections"][1].id
    assert t2.to_section_id == fx["sections"][2].id
    assert t2.is_post_factum is True
    assert t2.status == TransferStatus.accepted


async def test_auto_transfer_chain_through_double_transit(client, session) -> None:
    """Маршрут production_1 → transit_1(WIP) → transit_2(WIP) → production_2,
    все в РАЗНЫХ ГХП. При завершении production_1 должно создаться 3 передачи."""
    from app.transfers.services import auto_create_transfer_after_complete
    from app.models.internal_plan import InternalPlan, SectionPlanLine
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
        ProductionPlan,
        ProductionPlanStatus,
    )
    from datetime import date

    sku = "DBL-TRANSIT"
    qty = Decimal("7")

    sec_prod1 = Section(code=f"{sku}-P1", name="Prod1", kind="production", is_active=True, sort_order=0)
    sec_tr1 = Section(code=f"{sku}-TR1", name="Transit1", kind="wip_stock", is_active=True, sort_order=1)
    sec_tr2 = Section(code=f"{sku}-TR2", name="Transit2", kind="wip_stock", is_active=True, sort_order=2)
    sec_prod2 = Section(code=f"{sku}-P2", name="Prod2", kind="production", is_active=True, sort_order=3)
    session.add_all([sec_prod1, sec_tr1, sec_tr2, sec_prod2])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_b = StorageProductionGroup(code=f"{sku}-B", name="B", is_active=True, sort_order=1)
    spg_c = StorageProductionGroup(code=f"{sku}-C", name="C", is_active=True, sort_order=2)
    spg_d = StorageProductionGroup(code=f"{sku}-D", name="D", is_active=True, sort_order=3)
    session.add_all([spg_a, spg_b, spg_c, spg_d])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec_prod1.id, sort_order=0),
        SpgSection(spg_id=spg_b.id, section_id=sec_tr1.id, sort_order=0),
        SpgSection(spg_id=spg_c.id, section_id=sec_tr2.id, sort_order=0),
        SpgSection(spg_id=spg_d.id, section_id=sec_prod2.id, sort_order=0),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    st1 = RouteStage(route_id=route.id, sequence=1, section_id=sec_prod1.id, is_final=False, stage_kind="production")
    session.add(st1)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st1.id, sequence=1, operation_code="OP1", operation_name="OP1"))

    st_tr1 = RouteStage(route_id=route.id, sequence=2, section_id=None, storage_section_id=sec_tr1.id, is_final=False, stage_kind="transit")
    session.add(st_tr1)
    await session.flush()

    st_tr2 = RouteStage(route_id=route.id, sequence=3, section_id=None, storage_section_id=sec_tr2.id, is_final=False, stage_kind="transit")
    session.add(st_tr2)
    await session.flush()

    st2 = RouteStage(route_id=route.id, sequence=4, section_id=sec_prod2.id, is_final=True, stage_kind="production")
    session.add(st2)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st2.id, sequence=1, operation_code="OP2", operation_name="OP2"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
                          period_start=date(2026, 5, 1), period_end=date(2026, 5, 31))
    session.add(plan)
    await session.flush()

    pos = PlanPosition(production_plan_id=plan.id, product_id=product.id,
                       source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
                       quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
                       validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
                       period_start=plan.period_start, period_end=plan.period_end,
                       has_pack_ops=False, route_id=route.id, route_assigned_at=None)
    session.add(pos)
    await session.flush()

    ip = InternalPlan(production_plan_id=plan.id, release_batch_id=None)
    session.add(ip)
    await session.flush()

    line1 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                            section_id=sec_prod1.id, product_id=product.id,
                            route_id=route.id, route_stage_id=st1.id,
                            sequence=1, planned_quantity=qty)
    line_tr1 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                               section_id=sec_tr1.id, product_id=product.id,
                               route_id=route.id, route_stage_id=st_tr1.id,
                               sequence=2, planned_quantity=qty)
    line_tr2 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                               section_id=sec_tr2.id, product_id=product.id,
                               route_id=route.id, route_stage_id=st_tr2.id,
                               sequence=3, planned_quantity=qty)
    line2 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                            section_id=sec_prod2.id, product_id=product.id,
                            route_id=route.id, route_stage_id=st2.id,
                            sequence=4, planned_quantity=qty)
    session.add_all([line1, line_tr1, line_tr2, line2])
    await session.flush()

    task1 = WorkTask(section_plan_line_id=line1.id, section_id=sec_prod1.id,
                     product_id=product.id, route_stage_id=st1.id,
                     planned_quantity=qty, status=WorkTaskStatus.ready)
    session.add(task1)
    await session.flush()

    task2 = WorkTask(section_plan_line_id=line2.id, section_id=sec_prod2.id,
                     product_id=product.id, route_stage_id=st2.id,
                     planned_quantity=qty, status=WorkTaskStatus.waiting_previous)
    session.add(task2)
    await session.flush()

    await session.commit()

    user = await _make_user(session)

    result = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=qty,
        actor_id=user.id, idempotency_key="k-dbl-transit",
    )
    assert result is not None

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 3, f"Ожидалось 3 Transfer (chain через 2 transit), получили {len(transfers)}"

    t1 = transfers[0]
    assert t1.from_task_id == task1.id
    assert t1.from_section_id == sec_prod1.id
    assert t1.to_section_id == sec_tr1.id
    assert t1.is_post_factum is True
    assert t1.status == TransferStatus.accepted

    t2 = transfers[1]
    assert t2.from_section_id == sec_tr1.id
    assert t2.to_section_id == sec_tr2.id
    assert t2.is_post_factum is True
    assert t2.status == TransferStatus.accepted

    t3 = transfers[2]
    assert t3.to_task_id == task2.id
    assert t3.from_section_id == sec_tr2.id
    assert t3.to_section_id == sec_prod2.id
    assert t3.is_post_factum is True
    assert t3.status == TransferStatus.accepted


async def test_auto_transfer_no_chain_when_next_production_same_ghp(client, session) -> None:
    """Маршрут production_1 → transit(WIP) → production_2.
    transit и production_2 в ОДНОЙ ГХП (один SPG).
    После завершения production_1 должна создаться 1 передача (prod1 → transit),
    цепочка ДОЛЖНА остановиться, т.к. sections_share_spg(transit, prod2) = True."""
    from app.transfers.services import auto_create_transfer_after_complete
    from app.models.internal_plan import InternalPlan, SectionPlanLine
    from app.models.route import ProductionRoute, RouteStage, RouteOperation
    from app.models.techcard import Techcard, TechcardLine
    from app.models.production_plan import (
        PlanPosition,
        PlanPositionStatus,
        PlanPositionValidationStatus,
        PlanSourceType,
        ProductionPlan,
        ProductionPlanStatus,
    )
    from datetime import date

    sku = "SAME-GHP"
    qty = Decimal("6")

    sec_prod1 = Section(code=f"{sku}-P1", name="Prod1", kind="production", is_active=True, sort_order=0)
    sec_transit = Section(code=f"{sku}-TR", name="Transit", kind="wip_stock", is_active=True, sort_order=1)
    sec_prod2 = Section(code=f"{sku}-P2", name="Prod2", kind="production", is_active=True, sort_order=2)
    session.add_all([sec_prod1, sec_transit, sec_prod2])
    await session.flush()

    spg_a = StorageProductionGroup(code=f"{sku}-A", name="A", is_active=True, sort_order=0)
    spg_shared = StorageProductionGroup(code=f"{sku}-SH", name="Shared", is_active=True, sort_order=1)
    session.add_all([spg_a, spg_shared])
    await session.flush()
    session.add_all([
        SpgSection(spg_id=spg_a.id, section_id=sec_prod1.id, sort_order=0),
        SpgSection(spg_id=spg_shared.id, section_id=sec_transit.id, sort_order=0),
        SpgSection(spg_id=spg_shared.id, section_id=sec_prod2.id, sort_order=1),
    ])

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    st1 = RouteStage(route_id=route.id, sequence=1, section_id=sec_prod1.id, is_final=False, stage_kind="production")
    session.add(st1)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st1.id, sequence=1, operation_code="OP1", operation_name="OP1"))

    st_transit = RouteStage(route_id=route.id, sequence=2, section_id=None, storage_section_id=sec_transit.id, is_final=False, stage_kind="transit")
    session.add(st_transit)
    await session.flush()

    st2 = RouteStage(route_id=route.id, sequence=3, section_id=sec_prod2.id, is_final=True, stage_kind="production")
    session.add(st2)
    await session.flush()
    session.add(RouteOperation(route_stage_id=st2.id, sequence=1, operation_code="OP2", operation_name="OP2"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
                          period_start=date(2026, 5, 1), period_end=date(2026, 5, 31))
    session.add(plan)
    await session.flush()

    pos = PlanPosition(production_plan_id=plan.id, product_id=product.id,
                       source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
                       quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
                       validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
                       period_start=plan.period_start, period_end=plan.period_end,
                       has_pack_ops=False, route_id=route.id, route_assigned_at=None)
    session.add(pos)
    await session.flush()

    ip = InternalPlan(production_plan_id=plan.id, release_batch_id=None)
    session.add(ip)
    await session.flush()

    line1 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                            section_id=sec_prod1.id, product_id=product.id,
                            route_id=route.id, route_stage_id=st1.id,
                            sequence=1, planned_quantity=qty)
    line_transit = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                                   section_id=sec_transit.id, product_id=product.id,
                                   route_id=route.id, route_stage_id=st_transit.id,
                                   sequence=2, planned_quantity=qty)
    line2 = SectionPlanLine(internal_plan_id=ip.id, plan_position_id=pos.id,
                            section_id=sec_prod2.id, product_id=product.id,
                            route_id=route.id, route_stage_id=st2.id,
                            sequence=3, planned_quantity=qty)
    session.add_all([line1, line_transit, line2])
    await session.flush()

    task1 = WorkTask(section_plan_line_id=line1.id, section_id=sec_prod1.id,
                     product_id=product.id, route_stage_id=st1.id,
                     planned_quantity=qty, status=WorkTaskStatus.ready)
    session.add(task1)
    await session.flush()

    task2 = WorkTask(section_plan_line_id=line2.id, section_id=sec_prod2.id,
                     product_id=product.id, route_stage_id=st2.id,
                     planned_quantity=qty, status=WorkTaskStatus.waiting_previous)
    session.add(task2)
    await session.flush()

    await session.commit()

    user = await _make_user(session)

    result = await auto_create_transfer_after_complete(
        session, from_task=task1, good_quantity=qty,
        actor_id=user.id, idempotency_key="k-same-ghp",
    )
    assert result is not None

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert len(transfers) == 1, f"Ожидалась 1 Transfer (transit и prod2 в одной ГХП), получили {len(transfers)}"

    t = transfers[0]
    assert t.from_task_id == task1.id
    assert t.from_section_id == sec_prod1.id
    assert t.to_section_id == sec_transit.id
    assert t.is_post_factum is True
    assert t.status == TransferStatus.accepted

