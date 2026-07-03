"""Invariant checks for the Transfer ↔ Movement ↔ WorkTask.cached_*
data-consistency contract.

The production write-path maintains two projections of the same fact
("10 pcs moved from section A to section B"):

* ``transfers`` — a mutable business entity with lifecycle
  (status, sent/accepted/cancelled) that powers the UI and the
  ``/api/transfers`` endpoints.
* ``movements`` — an append-only event log.  A cross-GHP transfer
  writes one ``transfer_send`` row on the source and one
  ``transfer_receive`` row on the destination; ``cancel_transfer``
  deletes both rows and the ``WorkTask.cached_*`` caches are rebuilt
  from the surviving events by ``_refresh_task_cache``.

If any of the projections drifts, downstream aggregations
(``cached_available_quantity``, board UI, SPG snapshot) become
silently wrong.  These tests run seven invariant queries after
realistic e2e flows and fail with a precise diff on the first
violation.  The same queries are reused by the
``assert_no_invariants_violations`` helper, which the rest of the
test-suite can call from individual tests to assert local
invariants.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.transfer import Transfer
from app.models.user import User, UserRole
from app.models.work_task import WorkTask


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Inv Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}


# The seven invariant queries.  Each is shaped so that an empty
# result set is the "healthy" outcome.  Helper below prints the
# offending rows in a readable form so a test failure points at the
# exact row, not just "invariant X violated".
_INVARIANT_QUERIES: list[tuple[str, str]] = [
    (
        "1_movement_with_orphaned_transfer_id",
        """
        SELECT m.id AS movement_id, m.movement_type, m.transfer_id
        FROM movements m
        LEFT JOIN transfers t ON t.id = m.transfer_id
        WHERE m.transfer_id IS NOT NULL AND t.id IS NULL
        """,
    ),
    (
        "2_active_transfer_without_movements",
        """
        SELECT t.id AS transfer_id, t.status
        FROM transfers t
        LEFT JOIN movements m ON m.transfer_id = t.id
        WHERE t.status NOT IN ('cancelled', 'rejected')
        GROUP BY t.id, t.status
        HAVING count(m.id) = 0
        """,
    ),
    (
        "3_cancelled_transfer_with_surviving_movements",
        """
        SELECT t.id AS transfer_id, count(m.id) AS surviving_movements
        FROM transfers t
        JOIN movements m ON m.transfer_id = t.id
        WHERE t.status IN ('cancelled', 'rejected')
        GROUP BY t.id
        HAVING count(m.id) > 0
        """,
    ),
    (
        "4_active_transfer_with_wrong_movement_shape",
        """
        SELECT t.id AS transfer_id, t.status,
               count(*) FILTER (WHERE m.movement_type = 'transfer_send')    AS sends,
               count(*) FILTER (WHERE m.movement_type = 'transfer_receive') AS receives
        FROM transfers t
        LEFT JOIN movements m ON m.transfer_id = t.id
        WHERE t.status NOT IN ('cancelled', 'rejected')
        GROUP BY t.id, t.status
        HAVING count(*) FILTER (WHERE m.movement_type = 'transfer_send')    != 1
            OR count(*) FILTER (WHERE m.movement_type = 'transfer_receive') != 1
        """,
    ),
    # I5: Удалён на Этапе 3 — Movement больше не пишется shopfloor-операциями.
    # WorkTask.cached_* теперь считаются из StockTransaction через
    # StockProjectionManager.refresh_task_projection.,
    (
        "6_transfer_sent_qty_mismatches_movement_totals",
        """
        SELECT t.id AS transfer_id, t.status, t.sent_quantity,
               COALESCE(s.qty, 0) AS actual_send,
               COALESCE(r.qty, 0) AS actual_receive
        FROM transfers t
        LEFT JOIN (
            SELECT transfer_id, SUM(quantity) AS qty
            FROM movements WHERE movement_type = 'transfer_send'
            GROUP BY transfer_id
        ) s ON s.transfer_id = t.id
        LEFT JOIN (
            SELECT transfer_id, SUM(quantity) AS qty
            FROM movements WHERE movement_type = 'transfer_receive'
            GROUP BY transfer_id
        ) r ON r.transfer_id = t.id
        WHERE t.status NOT IN ('cancelled', 'rejected')
          AND (t.sent_quantity != COALESCE(s.qty, 0)
            OR t.sent_quantity != COALESCE(r.qty, 0))
        """,
    ),
    # I7: Удалён на Этапе 4 — WorkTask.cached_* колонки удалены.
    # SectionPlanLine.cached_* теперь вычисляются напрямую из StockTransaction
    # (см. _refresh_section_plan_line_cache в cache.py).
]


# ─── Stock Ledger invariants (v2, draft — active after Этап 1) ──────────────
# Эти инварианты проверяют целостность нового домена StockTransaction /
# StockBalance / WorkTask.completed_qty. Пока таблиц `stock_transactions`
# и `stock_balances` не существует (Этап 0), хелпер
# `assert_no_stock_ledger_invariants_violations` молча пропускает проверки.
# После создания таблиц на Этапе 1 инварианты включаются автоматически.

_STOCK_LEDGER_INVARIANT_QUERIES: list[tuple[str, str]] = [
    (
        "S1_stock_balance_equals_sum_of_transactions",
        """
        SELECT sb.product_id, sb.location_id, sb.quality_state,
               sb.balance_qty
                 - COALESCE(SUM(CASE WHEN st.to_location_id   = sb.location_id
                                          AND st.to_quality_state   = sb.quality_state
                                     THEN st.quantity END), 0)
                 + COALESCE(SUM(CASE WHEN st.from_location_id = sb.location_id
                                          AND st.from_quality_state = sb.quality_state
                                     THEN st.quantity END), 0)
                 AS diff
        FROM stock_balances sb
        LEFT JOIN stock_transactions st
          ON st.product_id = sb.product_id
         AND (st.to_location_id = sb.location_id OR st.from_location_id = sb.location_id)
        GROUP BY sb.product_id, sb.location_id, sb.quality_state, sb.balance_qty
        HAVING sb.balance_qty
                 != COALESCE(SUM(CASE WHEN st.to_location_id   = sb.location_id
                                           AND st.to_quality_state   = sb.quality_state
                                      THEN st.quantity END), 0)
                  - COALESCE(SUM(CASE WHEN st.from_location_id = sb.location_id
                                           AND st.from_quality_state = sb.quality_state
                                      THEN st.quantity END), 0)
        """,
    ),
    (
        "S2_no_orphan_stock_transaction_task",
        """
        SELECT st.id AS tx_id, st.task_id
        FROM stock_transactions st
        LEFT JOIN work_tasks wt ON wt.id = st.task_id
        WHERE st.task_id IS NOT NULL AND wt.id IS NULL
        """,
    ),
    (
        "S3_no_orphan_stock_transaction_transfer",
        """
        SELECT st.id AS tx_id, st.transfer_id
        FROM stock_transactions st
        LEFT JOIN transfers t ON t.id = st.transfer_id
        WHERE st.transfer_id IS NOT NULL AND t.id IS NULL
        """,
    ),
    (
        "S4_no_orphan_stock_transaction_location",
        """
        SELECT st.id AS tx_id, st.from_location_id, st.to_location_id
        FROM stock_transactions st
        WHERE st.from_location_id IS NOT NULL AND NOT EXISTS (
                  SELECT 1 FROM sections s WHERE s.id = st.from_location_id)
           OR st.to_location_id   IS NOT NULL AND NOT EXISTS (
                  SELECT 1 FROM sections s WHERE s.id = st.to_location_id)
        """,
    ),
    # S5_worktask_completed_qty_equals_transaction_sums — отключён до Этапа 4
    # (поля work_tasks.completed_qty / scrap_qty появятся только там).
    # После Этапа 4 добавить проверку:
    #   wt.completed_qty == SUM(st.quantity WHERE reason=COMPLETE AND quality=GOOD)
    #   wt.scrap_qty     == SUM(st.quantity WHERE reason=SCRAP)
    (
        "S6_transfer_balance_matches_transaction_sums",
        """
        SELECT t.id AS transfer_id, t.status, t.sent_quantity,
               COALESCE(s.net_send, 0) AS actual_send
        FROM transfers t
        LEFT JOIN (
            SELECT transfer_id,
                   SUM(CASE WHEN compensates_tx_id IS NULL THEN quantity
                             ELSE -quantity END) AS net_send
            FROM stock_transactions WHERE reason = 'TRANSFER_SEND'
            GROUP BY transfer_id
        ) s ON s.transfer_id = t.id
        WHERE t.status NOT IN ('cancelled', 'rejected')
          AND t.sent_quantity != COALESCE(s.net_send, 0)
        """,
    ),
]


async def _stock_ledger_tables_exist(session: AsyncSession) -> bool:
    """True если таблицы нового домена уже созданы миграцией Этапа 1."""
    result = await session.execute(text(
        "SELECT to_regclass('public.stock_transactions') IS NOT NULL "
        "AND to_regclass('public.stock_balances') IS NOT NULL AS exists"
    ))
    return bool(result.scalar())


async def assert_no_stock_ledger_invariants_violations(
    session: AsyncSession,
    *,
    context: str | None = None,
) -> None:
    """Запускает новые stock-ledger инварианты. No-op пока таблицы не
    созданы (Этап 0). После Этапа 1 — обязательная проверка в e2e-тестах.
    """
    if not await _stock_ledger_tables_exist(session):
        return
    prefix = f"[{context}] " if context else ""
    for name, sql in _STOCK_LEDGER_INVARIANT_QUERIES:
        result = await session.execute(text(sql))
        rows = [dict(row._mapping) for row in result]
        if rows:
            raise AssertionError(prefix + _format_violations(name, rows).lstrip())


def _format_violations(name: str, rows: Iterable[dict]) -> str:
    rows = list(rows)
    if not rows:
        return ""
    header = f"\n  Invariant '{name}' violated ({len(rows)} row(s)):"
    body = "\n    " + "\n    ".join(
        ", ".join(f"{k}={v!r}" for k, v in row.items()) for row in rows
    )
    return header + body


async def assert_no_invariants_violations(
    session: AsyncSession,
    *,
    context: str | None = None,
) -> None:
    """Run the seven invariant queries and raise AssertionError on the
    first violation.  ``context`` is a free-form label embedded in the
    error message so a test can show *which* step of its scenario
    drifted from the expected state.
    """
    prefix = f"[{context}] " if context else ""
    for name, sql in _INVARIANT_QUERIES:
        result = await session.execute(text(sql))
        rows = [dict(row._mapping) for row in result]
        if rows:
            raise AssertionError(prefix + _format_violations(name, rows).lstrip())
    # Новые stock-ledger инварианты (no-op пока таблицы не созданы на Этапе 1)
    await assert_no_stock_ledger_invariants_violations(session, context=context)


# ─── fixtures ───────────────────────────────────────────────────────────────


async def _make_two_ghp_route(
    session: AsyncSession,
    *,
    sku: str,
    qty: Decimal,
) -> dict:
    """Two production sections in two different SPGs — the minimal
    topology that makes a cross-GHP transfer possible.
    """
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
        st = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=sec.id,
            is_final=(idx == 2),
        )
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

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
        "sections": [sec1, sec2],
        "spgs": [spg_a, spg_b],
        "route": route,
    }


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post("/api/production-planning/rows/take-to-work", json={"position_ids": [position_id]})
    assert resp.status_code == 200, resp.text


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_empty_schema_passes_all_invariants(session: AsyncSession) -> None:
    """A schema with only the seeded system user has no Movements,
    Transfers or WorkTasks — every invariant query must return zero
    rows.  This guards against the queries themselves being
    ill-formed (e.g. cross-join explosion on empty input)."""
    await assert_no_invariants_violations(session, context="empty-schema")


async def test_take_to_work_with_remainder_allocation_stays_consistent(
    client, session: AsyncSession
) -> None:
    """``take-to-work`` with ``remainder_allocation`` that covers an
    earlier stage of the route must keep the Movement ledger and
    ``WorkTask.cached_*`` consistent.  We seed a remainder whose
    ``completed_stages_json`` says it has already been through
    step 1 (the first production step of this two-step route);
    on take-to-work, step 1 is auto-completed via
    ``Movement(type=complete, source_ref="auto_release_remainder")``
    and step 2 becomes ready.  The invariants we check are:

    * the auto-completed WorkTask's ``cached_completed_quantity``
      equals the sum of its ``Movement(type=complete)`` rows;
    * the second WorkTask is in ``ready`` and its cached_* are all 0;
    * no Transfer rows exist (remainder coverage is in-route, not a
      cross-section transfer)."""
    user = await _make_user(session, "inv-mrp@test.local")
    headers = _auth_headers(user)
    fx = await _make_two_ghp_route(session, sku="INV-MRP", qty=Decimal("4"))
    plan_pos = fx["position"]

    # Look up the operation_code of step 1 so the seeded remainder
    # has a matching completed_stages_json (the route_matcher checks
    # operation_code against SectionOperation.allowed_ops).
    step1_op = (await session.execute(
        text(
            "SELECT ro.operation_code "
            "FROM route_stages rs JOIN route_operations ro ON ro.route_stage_id = rs.id "
            "WHERE rs.route_id = :r AND rs.sequence = 1"
        ),
        {"r": fx["route"].id},
    )).scalar_one()

    from app.models.spg_remainder import SpgRemainder
    spg_section = (await session.execute(
        text("SELECT spg_id FROM spg_sections WHERE section_id = :s"),
        {"s": fx["sections"][0].id},
    )).scalar_one()
    remainder = SpgRemainder(
        product_id=fx["product"].id,
        spg_id=spg_section,
        route_stage_id=None,
        section_plan_line_id=None,
        origin_task_id=None,
        remainder_quantity=Decimal("4"),
        original_issued=Decimal("4"),
        completed_stages_json=[{
            "sequence": 1,
            "section_id": fx["sections"][0].id,
            "operation_code": step1_op,
            "operation_name": step1_op,
        }],
        source="manual_seed",
        created_by=1,
        created_by_user_name="seed",
    )
    session.add(remainder)
    await session.commit()

    await assert_no_invariants_violations(session, context="after-remainder-seed")

    # Launch the position, explicitly allocating the full remainder.
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={
            "position_ids": [plan_pos.id],
            "remainder_allocation": [{"remainder_id": remainder.id, "quantity": "4"}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    await assert_no_invariants_violations(session, context="after-take-to-work-with-remainder")

    # Step 1 must be auto-completed by the remainder coverage.
    # Verify via StockTransaction ledger (cached_* columns removed on Этап 4).
    from app.stock.models import Reason, StockTransaction
    from app.stock.services import StockProjectionManager

    auto_completed_tasks = (await session.execute(
        text(
            "SELECT id, status FROM work_tasks WHERE section_id = :s"
        ),
        {"s": fx["sections"][0].id},
    )).mappings().all()
    assert auto_completed_tasks, "Expected a WorkTask on the first section"
    pm = StockProjectionManager()
    for row in auto_completed_tasks:
        cache = await pm.get_task_cache(session, row["id"])
        stock_sum = await session.scalar(
            select(func.coalesce(func.sum(StockTransaction.quantity), 0))
            .where(
                StockTransaction.task_id == row["id"],
                StockTransaction.reason == Reason.complete,
            )
        ) or Decimal("0")
        assert cache["completed_quantity"] == stock_sum, (
            f"WorkTask {row['id']} cache.completed={cache['completed_quantity']} "
            f"diverges from SUM(StockTransaction.complete)={stock_sum}"
        )

    # Check auto_release_remainder via StockTransaction (source_ref tag)
    auto_release = (await session.execute(
        text(
            "SELECT task_id, quantity FROM stock_transactions "
            "WHERE source_ref = 'auto_release_remainder'"
        )
    )).mappings().all()
    for m in auto_release:
        cache = await pm.get_task_cache(session, m["task_id"])
        assert Decimal(m["quantity"]) == cache["completed_quantity"], (
            f"auto_release_remainder tx qty={m['quantity']} does not match "
            f"task {m['task_id']} cache.completed={cache['completed_quantity']}"
        )

    # Step 2 should be ready and have all-zero cached totals via ledger
    next_task = (await session.execute(
        text(
            "SELECT id, status FROM work_tasks WHERE section_id = :s"
        ),
        {"s": fx["sections"][1].id},
    )).mappings().one()
    assert next_task["status"] in {"ready", "waiting_previous"}
    next_cache = await pm.get_task_cache(session, next_task["id"])
    assert next_cache["received_quantity"] == Decimal("0")

    transfer_count = (await session.execute(text("SELECT count(*) FROM transfers"))).scalar_one()
    assert transfer_count == 0, \
        "In-route remainder coverage must NOT create a Transfer row"


# Old transfer-consistency tests (test_issue_complete_transfer_cancel_cycle,
# test_transfer_idempotency_phantom_movements, test_two_concurrent_transfers)
# were removed on Этап 2 — they relied on Movement invariants that no longer
# hold since transfer_send now writes only StockTransaction (no Movement).
