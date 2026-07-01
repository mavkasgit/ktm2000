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


async def _complete_first_task(
    client,
    task_id: int,
    qty: Decimal,
    idempotency_key: str | None = None,
    auto_transfer_next: bool = False,
) -> None:
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
    assert t.status == TransferStatus.sent


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
    await _complete_first_task(client, tasks[0].id, Decimal("3"), idempotency_key="k-same")

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
    await _complete_first_task(client, tasks[0].id, Decimal("2"), idempotency_key="k-fin")

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

    await _complete_first_task(client, task1.id, Decimal("3"), idempotency_key="k-flag-on", auto_transfer_next=True)

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

    await _complete_first_task(client, task1.id, Decimal("3"), idempotency_key="k-flag-off", auto_transfer_next=False)

    transfers = (await session.execute(select(Transfer))).scalars().all()
    assert transfers == [], "Без флага auto_transfer_next перемещение создаваться не должно"

