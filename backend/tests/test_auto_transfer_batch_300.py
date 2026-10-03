"""#300: авто-передача при завершении задачи — регрессия и замер SQL.

Кейс: маршрут «склад сырья → производственный участок СПГ-1 → производственный
участок СПГ-2». Выпуск плана создаёт задания на производственных этапах,
материал заводится приёмом на первый участок, затем ``complete_task
(auto_transfer_next=True)`` порождает авто-передачу на второй.

Разные СПГ — обязательное условие цикла (``sections_share_spg`` → break):
общий хелпер ``build_operation_route`` кладёт все участки в один СПГ, и с ним
передачи не бывает вовсе.

Снимок цепочки (#300) на этом кейсе измерен и ОТКАЧЕН: 96 → 97 SQL, ответ
идентичен. Условия выхода цикла и разбор — в
``docs/night/tickets/T-300-auto-transfer-batching.md``.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections import Counter
from decimal import Decimal

import pytest
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    SECTION_TYPE_RAW_STOCK,
)
from sqlalchemy import event, select

from tests.helpers.completed_operations import build_operation_route
from tests.helpers.transfers_chain import seed_manual_in
from tests.stock.helpers import record_transfer_receive
from tests.test_integrity_invariants import (
    _make_user,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)

pytestmark = pytest.mark.asyncio

RESULT_PATH = (
    r"C:\Users\LogoPrint\VibeCoding\ktm2000-night-a\docs\night\logs\measure_300_result.json"
)


async def _seed_chain(session, *, sku: str):
    """RAW → P1 → P2, причём P1 и P2 в РАЗНЫХ СПГ."""
    fx = await build_operation_route(
        session,
        sku=sku,
        qty=Decimal(100),
        stages=[
            (f"{sku}-RAW", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            (f"{sku}-P1", SECTION_TYPE_PRODUCTION, ["P1_OP"]),
            (f"{sku}-P2", SECTION_TYPE_PRODUCTION, ["P2_OP"]),
        ],
    )
    raw, p1, p2 = fx["sections"]
    # Вынос P2 в отдельный СПГ: иначе sections_share_spg(P1, P2) истинен и цикл
    # авто-передачи выходит на первом же шаге.
    other_spg = StorageProductionGroup(
        code=f"{sku}-SPG2", name="СПГ 2", is_active=True, sort_order=1
    )
    session.add(other_spg)
    await session.flush()
    p2_link = await session.scalar(
        select(SpgSection).where(SpgSection.section_id == p2.id)
    )
    p2_link.spg_id = other_spg.id

    await session.refresh(fx["position"])
    released = await create_release_batch(
        session, production_plan_id=fx["plan"].id, positions=None
    )
    await release_batch(session, released["id"])
    return fx, raw, p1, p2


async def _prepare(session, *, sku: str):
    """Цепочка + материал, заведённый приёмом на первый участок."""
    fx, raw, p1, _p2 = await _seed_chain(session, sku=sku)
    user = await _make_user(session, f"{sku.lower()}@local")
    ops_raw = await completed_operations_through_stage(
        session, route_id=fx["route"].id, through_sequence=1
    )
    await seed_manual_in(
        session,
        user_id=user.id,
        location_id=raw.id,
        product_id=fx["product"].id,
        quantity=Decimal(100),
        completed_operations=ops_raw,
    )
    p1_task = (
        (
            await session.execute(
                select(WorkTask).where(
                    WorkTask.section_id == p1.id,
                    WorkTask.status == WorkTaskStatus.ready,
                )
            )
        )
        .scalars()
        .first()
    )
    assert p1_task is not None, "на производственном участке должно быть задание"
    # Приём заводит issued_quantity задания (без task_id complete_task падает)
    # и кладёт остаток в ops-группе «до своего этапа», откуда его и возьмёт
    # TRANSFER_SEND. Подпись — по этапу ИСТОЧНИКА: она описывает, что уходит
    # из сырья, а не что приходит на участок (ADR-0055).
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=raw.id,
        to_location_id=p1.id,
        quantity=Decimal(100),
        task_id=p1_task.id,
        created_by=user.id,
        completed_operations=ops_raw,
    )
    return fx, user, p1, p1_task


async def _transfers_payload(session) -> list[dict]:
    rows = (
        (await session.execute(select(Transfer).order_by(Transfer.id))).scalars().all()
    )
    return [
        {
            "from_task_id": t.from_task_id,
            "to_task_id": t.to_task_id,
            "quantity": str(t.sent_quantity),
            "dimensions": t.dimensions,
            "accepted_quantity": (
                str(t.accepted_quantity) if t.accepted_quantity is not None else None
            ),
            "rejected_quantity": (
                str(t.rejected_quantity) if t.rejected_quantity is not None else None
            ),
            "status": getattr(t.status, "value", t.status),
        }
        for t in rows
    ]


async def _run_case(session, *, sku: str) -> tuple[dict, list[dict]]:
    from app.services.shopfloor.operations_tasks import complete_task

    _fx, user, _p1, p1_task = await _prepare(session, sku=sku)

    kinds: Counter[str] = Counter()
    sync_engine = session.bind.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        kinds[statement.lstrip().split(" ", 1)[0].upper()] += 1

    try:
        await complete_task(
            session,
            task_id=p1_task.id,
            good_quantity=Decimal(100),
            defect_quantity=Decimal(0),
            actor_id=user.id,
            comment="T300",
            auto_transfer_next=True,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    payload = await _transfers_payload(session)
    await assert_no_invariants_violations(session, context=sku)
    await assert_no_stock_ledger_invariants_violations(session, context=sku)
    return {"kinds": dict(kinds), "total": sum(kinds.values())}, payload


@pytest.mark.asyncio
async def test_measure_auto_transfer_sql(session) -> None:
    """Замер: SQL по глаголам и созданные передачи (вход для сверки)."""
    measured, payload = await _run_case(session, sku="T300")
    assert payload, "кейс обязан породить авто-передачу, иначе он пустой"
    print(f"\nT300: {measured} SQL по глаголам")
    for row in payload:
        print(f"   {row}")

    await asyncio.to_thread(
        pathlib.Path(RESULT_PATH).write_text,
        json.dumps(
            {"measured": measured, "transfers": payload},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        "utf-8",
    )
