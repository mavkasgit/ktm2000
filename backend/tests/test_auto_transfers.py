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
        quantity=qty, source_payload={}, status=PlanPositionStatus.released,
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


# Tests will be added in subsequent steps.
