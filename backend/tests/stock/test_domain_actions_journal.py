"""Тесты журналирования доменных операций в action_journal (ADR-0019, #116, волна A).

Покрывают:
- complete_task (good+scrap+transform-порция) — один Action(task_complete),
  все проводки с его action_id
- depends_on-цепочка задачи: каждое новое действие по задаче зависит от
  последнего active (решение 3 спеки)
- final_release — Action(final_release) по цепочке
- defect_decide — Action(defect_decision, ref_id=defect.id)
- return_to_stock (endpoint) — Action(return_to_stock) по цепочке
- ручная корректировка — Action(manual_adjustment, ref_id=None)
- импорт остатков — ОДИН Action(import_remainders) на батч (обе фазы),
  source_ref=f"import_remainders:{id}" (решение 5)
- seed_demo — один Action на весь сид, компенсатора нет (решение 7)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action
from app.models.work_task import WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService
from app.stock.import_service import RemainderItem, apply_remainders_import
from app.stock.models import StockTransaction
from app.seeds.seeders.spgs_seeder import seed_spgs
from tests.stock.helpers import FAKE_DEFECT_DECISION_MAP, FAKE_SCRAP_KWARGS, record_transfer_receive
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _issue_material(session: AsyncSession, fx: dict, qty: Decimal = Decimal("10")) -> None:
    """Выдать материал на задание: MANUAL_IN на склад + TRANSFER_RECEIVE на задачу."""
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
        to_location_id=fx["task"].section_id,
        quantity=qty,
        task_id=fx["task"].id,
        created_by=fx["user"].id,
    )
    fx["task"].status = WorkTaskStatus.in_progress
    await session.commit()


async def _task_actions(session: AsyncSession, task_id: int) -> list[Action]:
    return (await session.execute(
        select(Action)
        .where(Action.ref_id == task_id)
        .order_by(Action.id)
    )).scalars().all()


async def test_complete_task_creates_action(session: AsyncSession) -> None:
    """complete_task (good+scrap) = один Action; обе проводки с его action_id."""
    from app.services.shopfloor.operations_tasks import complete_task

    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)
    task = fx["task"]

    result = await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("7"),
        defect_quantity=Decimal("3"),
        actor_id=fx["user"].id,
        defect_reason="test_scrap",
        **FAKE_SCRAP_KWARGS,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-complete")

    actions = (await session.execute(
        select(Action).where(
            Action.action_type == "task_complete",
            Action.ref_id == task.id,
        )
    )).scalars().all()
    assert len(actions) == 1
    action = actions[0]
    assert action.status == "active"
    assert action.depends_on == []

    txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.action_id == action.id,
        )
    )).scalars().all()
    assert len(txs) == 2
    assert {tx.reason for tx in txs} == {Reason.COMPLETE, Reason.SCRAP}
    assert sorted(tx.id for tx in txs) == sorted(result["transaction_ids"])


async def test_task_chain_depends_on(session: AsyncSession, ) -> None:
    """Цепочка задачи: complete → final_release → return_to_stock, каждое
    следующее действие depends_on от последнего active (решение 3)."""
    from app.api.routes.shopfloor import ReturnRemainderPayload, return_remainder
    from app.services.shopfloor.operations_tasks import complete_task, final_release

    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)
    task = fx["task"]

    await complete_task(
        session,
        task_id=task.id,
        good_quantity=Decimal("8"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    await final_release(
        session,
        task_id=task.id,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    await return_remainder(
        ReturnRemainderPayload(task_id=task.id, quantity=Decimal("2")),
        db=session,
        current_user=fx["user"],
        locked_section_id=None,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-chain")

    actions = await _task_actions(session, task.id)
    by_type = {a.action_type: a for a in actions}
    assert set(by_type) == {"task_complete", "final_release", "return_to_stock"}
    ordered = [by_type["task_complete"], by_type["final_release"], by_type["return_to_stock"]]
    assert ordered[0].depends_on == []
    assert ordered[1].depends_on == [ordered[0].id]
    assert ordered[2].depends_on == [ordered[1].id]
    assert all(a.status == "active" for a in ordered)

    # Все проводки каждого действия несут его action_id.
    for action in ordered:
        txs = (await session.execute(
            select(StockTransaction).where(StockTransaction.action_id == action.id)
        )).scalars().all()
        assert txs, f"нет проводок у {action.action_type}"


async def test_defect_decision_creates_action(session: AsyncSession) -> None:
    """defect_decide (scrap) = Action(defect_decision, ref_id=defect.id)."""
    from app.models.defect import Defect
    from app.models.defect import DefectDecisionType
    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)

    res = await create_defect(
        session,
        task_id=fx["task"].id,
        quantity=Decimal("2"),
        actor_id=fx["user"].id,
        reason="scratch",
    )
    defect_id = res["defect_id"]

    decision = await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=DefectDecisionType.scrap,
        quantity=Decimal("2"),
        actor_id=fx["user"].id,
        defect_decision_map=FAKE_DEFECT_DECISION_MAP,
        **FAKE_SCRAP_KWARGS,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-defect-decision")

    action = (await session.execute(
        select(Action).where(
            Action.action_type == "defect_decision",
            Action.ref_id == defect_id,
        )
    )).scalars().one()
    assert action.status == "active"

    tx = await session.get(StockTransaction, decision["stock_transaction_id"]) \
        if "stock_transaction_id" in decision else None
    if tx is None:
        defect = await session.get(Defect, defect_id)
        tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.SCRAP
    assert tx.action_id == action.id


async def test_manual_adjustment_creates_action(client, session: AsyncSession) -> None:
    """Ручная корректировка = Action(manual_adjustment) без ref_id."""
    from app.models import Product, ProductType, Section

    product = Product(sku="AJ-ADJ", name="AJ-ADJ", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    location = Section(code="AJ-ADJ-LOC", name="AJ-ADJ-LOC", type="raw_stock", is_active=True, sort_order=0)
    session.add(location)
    await session.commit()

    resp = await client.post("/api/stock/adjustment", json={
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 4.0,
        "reason": "manual_in",
        "quality_state": "good",
    })
    assert resp.status_code == 201, resp.text

    action = (await session.execute(
        select(Action).where(Action.action_type == "manual_adjustment")
    )).scalars().one()
    assert action.ref_id is None
    assert action.status == "active"

    tx = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.reason == Reason.MANUAL_IN,
            StockTransaction.product_id == product.id,
        )
    )).scalars().one()
    assert tx.action_id == action.id
    await assert_no_invariants_violations(session, context="aj-manual-adjustment")


async def test_import_remainders_single_action(session: AsyncSession) -> None:
    """Импорт-батч (очистка + заливка) = один Action; source_ref по решению 5."""
    from app.models import Product, ProductType, Section

    sku = "AJ-IMP"
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    location = Section(code="AJ-IMP-LOC", name="AJ-IMP-LOC", type="raw_stock", is_active=True, sort_order=0)
    session.add(location)
    await session.commit()

    # Существующий баланс, чтобы фаза очистки породила ADJUSTMENT_OUT.
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=None,
        to_location_id=location.id,
        quantity=Decimal("9"),
        reason=Reason.MANUAL_IN,
        created_by=1,
    ))
    await session.commit()

    items = [
        RemainderItem(
            source_row_number=2,
            sku=sku,
            quantity=5.0,
            comment=None,
            product_id=None,
            product_name=None,
            status="valid",
            errors=[],
            raw_values=[],
        ),
    ]
    result = await apply_remainders_import(session, location.id, items, clear_existing=True)
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-import")

    assert result.success is True
    assert result.id is not None
    assert len(result.transaction_ids) == 2  # ADJUSTMENT_OUT + MANUAL_IN

    actions = (await session.execute(
        select(Action).where(Action.action_type == "import_remainders")
    )).scalars().all()
    assert len(actions) == 1
    action = actions[0]
    assert action.id == result.id
    assert action.ref_id == action.id

    txs = (await session.execute(
        select(StockTransaction).where(StockTransaction.id.in_(result.transaction_ids))
    )).scalars().all()
    assert len(txs) == 2
    assert {tx.reason for tx in txs} == {Reason.ADJUSTMENT_OUT, Reason.MANUAL_IN}
    assert all(tx.action_id == action.id for tx in txs)
    assert all(tx.source_ref == f"import_remainders:{result.id}" for tx in txs)


async def test_seed_demo_creates_one_action(session: AsyncSession, monkeypatch) -> None:
    """Демо-сид: один Action('seed_demo'), все его MANUAL_IN с его action_id
    (решения 2 и 7: компенсатора нет — попытка reverse вернёт NotAllowed)."""
    from tests.test_prep_stock_seed import (
        _build_route_with_sections,
        _seed_default_sections,
        _spg_defs,
    )
    from app.seeds.seeders import demo_production_seeder
    from app.models.user import User, UserRole

    actor = User(
        username="aj-seed-actor",
        email="aj-seed-actor@local",
        full_name="AJ Seed Actor",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(actor)
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, _spg_defs(), sections_map)
    await session.commit()

    await _build_route_with_sections(
        session,
        route_code="dynamic_packaging_map_rp",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("DRILLING", "Сверловка", "production", True),
            ("PRESSING", "Пресс", "production", True),
            ("SHOT_BLAST", "Дробеструй", "production", True),
            ("WIP_WH", "Склад пф", "wip_stock", False),
        ],
    )

    stats = await demo_production_seeder.seed_demo_production(session)
    await session.commit()
    await assert_no_invariants_violations(session, context="aj-seed-demo")

    assert stats["remainders"] >= 1

    actions = (await session.execute(
        select(Action).where(Action.action_type == "seed_demo")
    )).scalars().all()
    assert len(actions) == 1
    action = actions[0]
    assert action.ref_id is None

    seed_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.reason == Reason.MANUAL_IN,
            StockTransaction.action_id == action.id,
        )
    )).scalars().all()
    assert len(seed_txs) == stats["remainders"]


