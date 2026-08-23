"""Тесты StockActionCompensator — универсальный компенсатор доменных
действий shopfloor/плана/импорта (ADR-0019, тикет #116, волна B).

Покрывает:
- task_complete: preview (зеркальная геометрия) + reverse 1:1 с reverses_id;
- цепочка задачи: reverse промежуточного узла → HasDependentActions;
  reverse всей цепочки cascade=True в обратном топологическом порядке;
- defect_decision, manual_adjustment (ref_id=None), import_remainders
  (обе фазы одним reverse), final_release/return_to_stock (через цепочку);
- seed_demo: компенсатора нет → NotAllowed (решение 7);
- net ≥ 0 до/после + assert_no_invariants_violations в каждом тесте.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.reversal import errors
from app.reversal.service import _sign_payload, reversal_service
from app.stock.import_service import RemainderItem, apply_remainders_import
from app.stock.models import Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from tests.stock.helpers import FAKE_DEFECT_DECISION_MAP, FAKE_SCRAP_KWARGS, record_transfer_receive
from tests.stock.test_domain_actions_journal import _issue_material
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _balance(session: AsyncSession, location_id: int, product_id: int) -> Decimal:
    return (await session.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
            StockBalance.location_id == location_id,
            StockBalance.product_id == product_id,
        )
    )) or Decimal("0")


async def _action_txs(session: AsyncSession, action_id: int) -> list[StockTransaction]:
    return (await session.execute(
        select(StockTransaction).where(StockTransaction.action_id == action_id)
        .order_by(StockTransaction.id)
    )).scalars().all()


async def _complete_task(
    session: AsyncSession, fx: dict, *, good: Decimal, scrap: Decimal
) -> Action:
    from app.services.shopfloor.operations_tasks import complete_task

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=good,
        defect_quantity=scrap,
        actor_id=fx["user"].id,
        defect_reason="test_scrap" if scrap > 0 else None,
        **FAKE_SCRAP_KWARGS,
    )
    await session.commit()
    return (await session.execute(
        select(Action).where(
            Action.action_type == "task_complete",
            Action.ref_id == fx["task"].id,
        )
    )).scalar_one()


async def _task_chain(
    session: AsyncSession, fx: dict
) -> dict[str, Action]:
    """Цепочка complete → final_release → return_to_stock (решение 3)."""
    from app.api.routes.shopfloor import ReturnRemainderPayload, return_remainder
    from app.services.shopfloor.operations_tasks import final_release

    complete = await _complete_task(session, fx, good=Decimal("8"), scrap=Decimal("0"))

    await final_release(
        session, task_id=fx["task"].id, quantity=Decimal("5"), actor_id=fx["user"].id,
    )
    await session.commit()

    await return_remainder(
        ReturnRemainderPayload(task_id=fx["task"].id, quantity=Decimal("2")),
        db=session,
        current_user=fx["user"],
        locked_section_id=None,
    )
    await session.commit()

    actions = (await session.execute(
        select(Action).where(Action.ref_id == fx["task"].id).order_by(Action.id)
    )).scalars().all()
    by_type = {a.action_type: a for a in actions}
    assert set(by_type) == {"task_complete", "final_release", "return_to_stock"}
    assert by_type["final_release"].depends_on == [complete.id]
    assert by_type["return_to_stock"].depends_on == [by_type["final_release"].id]
    return {
        "complete": complete,
        "final_release": by_type["final_release"],
        "return_to_stock": by_type["return_to_stock"],
    }


def _forged_reverse_token(action_id: int, fp: str) -> str:
    """Валидно подписанный токен без preview (для проверки guard-путей)."""
    return _sign_payload(
        {"action_id": action_id, "cascade": False, "kind": "reverse", "fp": fp}
    )


async def test_task_complete_reverse_mirrors_entries(session: AsyncSession) -> None:
    """reverse(task_complete): зеркальные проводки 1:1 с reverses_id,
    локации перевёрнуты; остатки возвращаются к состоянию до операции."""
    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)
    section_id = fx["task"].section_id
    product_id = fx["product"].id
    pre_section = await _balance(session, section_id, product_id)

    action = await _complete_task(session, fx, good=Decimal("7"), scrap=Decimal("3"))
    orig_txs = await _action_txs(session, action.id)
    assert len(orig_txs) == 2
    assert {t.reason for t in orig_txs} == {Reason.COMPLETE, Reason.SCRAP}
    scrap_loc = next(t.to_location_id for t in orig_txs if t.reason == Reason.SCRAP)
    assert await _balance(session, scrap_loc, product_id) == Decimal("3")

    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    assert preview.plan_token
    assert preview.revert[0].id == action.id

    result = await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-complete-rev")

    assert result.reversed_action_ids == [action.id]
    comp_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.reverses_id.in_([t.id for t in orig_txs])
        )
    )).scalars().all()
    assert len(comp_txs) == len(orig_txs)
    by_source = {c.reverses_id: c for c in comp_txs}
    for orig in orig_txs:
        mirror = by_source[orig.id]
        assert mirror.product_id == orig.product_id
        assert mirror.quantity == orig.quantity
        assert mirror.from_location_id == orig.to_location_id
        assert mirror.to_location_id == orig.from_location_id
        assert mirror.action_id == result.reversal_action_id

    refreshed = await session.get(Action, action.id)
    assert refreshed.status == ActionStatus.REVERSED
    assert refreshed.reversed_by_action_id == result.reversal_action_id

    # Остатки: scrap опустел, участок вернулся к состоянию до complete.
    assert await _balance(session, scrap_loc, product_id) == Decimal("0")
    assert await _balance(session, section_id, product_id) == pre_section

async def test_reverse_intermediate_blocked_has_dependents(
    session: AsyncSession,
) -> None:
    """Reverse промежуточного узла цепочки → блокер has_dependents
    с полной цепочкой; confirm без cascade невозможен (preview-first)."""
    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx, qty=Decimal("30"))
    chain = await _task_chain(session, fx)

    preview = await reversal_service.preview_reverse(session, chain["complete"].id)
    assert preview.plan_token is None
    kinds = [b.kind for b in preview.blockers]
    assert "has_dependents" in kinds
    blocker = next(b for b in preview.blockers if b.kind == "has_dependents")
    assert set(blocker.chain) == {chain["final_release"].id, chain["return_to_stock"].id}

    fp = await reversal_service._fingerprint(session, [chain["complete"].id])
    with pytest.raises(errors.HasDependentActions) as exc_info:
        await reversal_service.reverse(
            session,
            chain["complete"].id,
            plan_token=_forged_reverse_token(chain["complete"].id, fp),
        )
    assert set(exc_info.value.chain) == {
        chain["final_release"].id, chain["return_to_stock"].id,
    }
    await assert_no_invariants_violations(session, context="ac-dependent-block")


async def test_reverse_full_chain_cascade_topological_order(
    session: AsyncSession,
) -> None:
    """Каскадная отмена всей цепочки задачи в обратном топологическом
    порядке; остатки возвращаются к состоянию до цепочки."""
    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx, qty=Decimal("30"))
    section_id = fx["task"].section_id
    product_id = fx["product"].id
    pre_section = await _balance(session, section_id, product_id)

    chain = await _task_chain(session, fx)
    await assert_no_invariants_violations(session, context="ac-chain-before")

    preview = await reversal_service.preview_reverse(
        session, chain["complete"].id, cascade=True
    )
    assert {n.id for n in preview.revert} == {
        chain["complete"].id, chain["final_release"].id, chain["return_to_stock"].id,
    }

    result = await reversal_service.reverse(
        session, chain["complete"].id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-chain-rev")

    # Обратный топологический порядок: dependents раньше зависимостей.
    assert result.reversed_action_ids == [
        chain["return_to_stock"].id,
        chain["final_release"].id,
        chain["complete"].id,
    ]
    for aid in result.reversed_action_ids:
        refreshed = await session.get(Action, aid)
        assert refreshed.status == ActionStatus.REVERSED
    # Каждое действие получило свои компенсирующие проводки (у каждого
    # узла — собственный reversal-Action).
    for aid in result.reversed_action_ids:
        orig_ids = {t.id for t in await _action_txs(session, aid)}
        mirrored = (await session.execute(
            select(func.count(StockTransaction.id)).where(
                StockTransaction.reverses_id.in_(orig_ids)
            )
        )).scalar_one()
        assert mirrored == len(orig_ids), f"действие #{aid} компенсировано не полностью"

    assert await _balance(session, section_id, product_id) == pre_section


async def test_defect_decision_reverse(session: AsyncSession) -> None:
    """reverse(defect_decision): scrap-проводка компенсируется зеркально."""
    from app.models.defect import Defect, DefectDecisionType
    from app.services.shopfloor.operations_defects import create_defect, defect_decide

    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)

    res = await create_defect(
        session, task_id=fx["task"].id, quantity=Decimal("2"),
        actor_id=fx["user"].id, reason="scratch",
    )
    defect_id = res["defect_id"]
    await defect_decide(
        session, defect_id=defect_id, decision_type=DefectDecisionType.scrap,
        quantity=Decimal("2"), actor_id=fx["user"].id,
        defect_decision_map=FAKE_DEFECT_DECISION_MAP, **FAKE_SCRAP_KWARGS,
    )
    await session.commit()

    action = (await session.execute(
        select(Action).where(
            Action.action_type == "defect_decision", Action.ref_id == defect_id,
        )
    )).scalar_one()
    orig_txs = await _action_txs(session, action.id)
    scrap_loc = orig_txs[0].to_location_id
    product_id = fx["product"].id
    assert await _balance(session, scrap_loc, product_id) == Decimal("2")

    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    result = await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-defect-rev")

    assert result.reversed_action_ids == [action.id]
    mirror = (await session.execute(
        select(StockTransaction).where(StockTransaction.reverses_id == orig_txs[0].id)
    )).scalar_one()
    assert mirror.from_location_id == scrap_loc
    assert mirror.quantity == orig_txs[0].quantity
    assert await _balance(session, scrap_loc, product_id) == Decimal("0")


async def test_manual_adjustment_reverse(client, session: AsyncSession) -> None:
    """reverse(manual_adjustment): действие без ref_id отменяется по
    идентификатору узла; остаток возвращается к нулю."""
    from app.models import Product, ProductType, Section

    product = Product(sku="AC-ADJ", name="AC-ADJ", type=ProductType.finished_good,
                      unit="pcs", is_active=True)
    session.add(product)
    location = Section(code="AC-ADJ-LOC", name="AC-ADJ-LOC", type="raw_stock",
                       is_active=True, sort_order=0)
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
    await session.commit()

    action = (await session.execute(
        select(Action).where(Action.action_type == "manual_adjustment")
    )).scalars().one()
    assert action.ref_id is None
    orig_txs = await _action_txs(session, action.id)
    assert await _balance(session, location.id, product.id) == Decimal("4")

    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    result = await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-manual-rev")

    assert result.reversed_action_ids == [action.id]
    mirror = (await session.execute(
        select(StockTransaction).where(StockTransaction.reverses_id == orig_txs[0].id)
    )).scalar_one()
    assert mirror.from_location_id == location.id
    assert mirror.to_location_id is None
    assert await _balance(session, location.id, product.id) == Decimal("0")


async def test_import_remainders_reverse_both_phases(session: AsyncSession) -> None:
    """Один reverse(import_remainders) компенсирует обе фазы: и очистку
    (ADJUSTMENT_OUT), и заливку (MANUAL_IN); остаток = до импорта."""
    from app.models import Product, ProductType, Section

    sku = "AC-IMP"
    product = Product(sku=sku, name=sku, type=ProductType.finished_good,
                      unit="pcs", is_active=True)
    session.add(product)
    location = Section(code="AC-IMP-LOC", name="AC-IMP-LOC", type="raw_stock",
                       is_active=True, sort_order=0)
    session.add(location)
    await session.commit()

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
    pre = await _balance(session, location.id, product.id)
    assert pre == Decimal("9")

    items = [
        RemainderItem(
            source_row_number=2, sku=sku, quantity=5.0, comment=None,
            product_id=None, product_name=None, status="valid", errors=[],
            raw_values=[],
        ),
    ]
    result = await apply_remainders_import(session, location.id, items, clear_existing=True)
    await session.commit()
    assert result.success is True

    action = await session.get(Action, result.action_id)
    assert action is not None and action.action_type == "import_remainders"
    assert await _balance(session, location.id, product.id) == Decimal("5")

    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    rev = await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-import-rev")

    assert rev.reversed_action_ids == [action.id]
    orig_txs = await _action_txs(session, action.id)
    assert {t.reason for t in orig_txs} == {Reason.ADJUSTMENT_OUT, Reason.MANUAL_IN}
    mirrored = {t.reverses_id for t in await _action_txs(session, rev.reversal_action_id)}
    assert {t.id for t in orig_txs} <= mirrored
    assert await _balance(session, location.id, product.id) == pre


async def test_seed_demo_reverse_not_allowed(session: AsyncSession, monkeypatch) -> None:
    """seed_demo без компенсатора (решение 7): preview 🚫 not_allowed,
    confirm → NotAllowed."""
    from app.models.user import User, UserRole
    from app.seeds.seeders import demo_production_seeder
    from app.seeds.seeders.spgs_seeder import seed_spgs
    from tests.test_prep_stock_seed import (
        _build_route_with_sections,
        _seed_default_sections,
        _spg_defs,
    )

    actor = User(
        username="ac-seed-actor", email="ac-seed-actor@local",
        full_name="AC Seed Actor", role=UserRole.admin, is_active=True,
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
    assert stats["remainders"] >= 1

    action = (await session.execute(
        select(Action).where(Action.action_type == "seed_demo")
    )).scalars().one()

    preview = await reversal_service.preview_reverse(session, action.id)
    assert preview.plan_token is None
    assert [b.kind for b in preview.blockers] == ["not_allowed"]
    assert "seed_demo" in preview.blockers[0].detail

    fp = await reversal_service._fingerprint(session, [action.id])
    with pytest.raises(errors.NotAllowed, match="seed_demo"):
        await reversal_service.reverse(
            session, action.id, plan_token=_forged_reverse_token(action.id, fp),
        )
    await assert_no_invariants_violations(session, context="ac-seed-not-allowed")

async def test_plan_auto_release_tree_preview_reverse(session: AsyncSession) -> None:
    """Семья plan_auto_release покрыта компенсатором: tree показывает её
    зависимой от complete, preview complete блокирован has_dependents,
    reverse(plan_auto_release) зеркалит COMPLETE-проводку.

    Ветка planned_qty<=0 в plan_generation.py недостижима тестом
    (MRP-аллокация остатков удалена, covered_qty≡0), поэтому Action
    синтетический — создаётся так же, как в самой ветке."""
    from app.services.action_journal_service import action_journal_service

    fx = await _setup_minimal_route(session)
    await _issue_material(session, fx)
    section_id = fx["task"].section_id
    product_id = fx["product"].id
    pre_section = await _balance(session, section_id, product_id)

    complete = await _complete_task(session, fx, good=Decimal("7"), scrap=Decimal("0"))

    action = await action_journal_service.log_task_action(
        session,
        action_type="plan_auto_release",
        ref_id=fx["task"].id,
        actor="tester",
    )
    svc = StockCommandService()
    tx = await svc.record(session, StockCommand(
        product_id=fx["task"].product_id,
        from_location_id=None,
        to_location_id=section_id,
        quantity=Decimal("3"),
        reason=Reason.COMPLETE,
        task_id=fx["task"].id,
        source_ref="auto_release_remainder",
        created_by=fx["user"].id,
        action_id=action.id,
    ))
    await session.commit()

    # tree: план-автозавершение — dependents узла complete.
    tree = await reversal_service.tree(session, complete.id)
    assert [c.action_type for c in tree.root.children] == ["plan_auto_release"]

    # Reverse промежуточного узла блокирован has_dependents.
    blocked = await reversal_service.preview_reverse(session, complete.id)
    assert blocked.plan_token is None
    assert "has_dependents" in [b.kind for b in blocked.blockers]

    assert await _balance(session, section_id, product_id) == pre_section + Decimal("3")
    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    result = await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="ac-plan-auto-release")

    assert result.reversed_action_ids == [action.id]
    mirror = (await session.execute(
        select(StockTransaction).where(StockTransaction.reverses_id == tx.id)
    )).scalar_one()
    assert mirror.from_location_id == section_id
    assert mirror.to_location_id is None
    assert mirror.quantity == Decimal("3")
    refreshed = await session.get(Action, action.id)
    assert refreshed.status == ActionStatus.REVERSED
    assert await _balance(session, section_id, product_id) == pre_section


async def test_ref_fallback_ambiguous_returns_not_found(session: AsyncSession) -> None:
    """Fallback по (action_type, ref_id) без action_id: узел возвращается
    только если активное действие ровно одно; при двух активных — not_found
    вместо тихой выборки первой записи."""
    from app.reversal.action_compensator import StockActionCompensator
    from app.services.action_journal_service import action_journal_service

    comp = StockActionCompensator("task_complete")
    ref = 987654
    j1 = await action_journal_service.log(
        session, action_type="task_complete", ref_id=ref,
    )
    single = await comp.check(session, ref)
    assert single.ok and single.node_id == j1.id

    await action_journal_service.log(
        session, action_type="task_complete", ref_id=ref,
    )
    ambiguous = await comp.check(session, ref)
    assert not ambiguous.ok
    assert [b.kind for b in ambiguous.blockers] == ["not_found"]
