"""#300: авто-передача при завершении задачи — проверка поведения.

Завершение задания на производственном участке переносит факт на следующий
участок ДРУГОГО СПГ: создаётся передача, факт уходит, ledger сходится.

Тест ловит все условия выхода цикла
``auto_create_transfer_after_complete``: без разнесённых по СПГ участков
(``sections_share_spg`` рвёт цикл), без приёма на участок
(``issued_quantity``) и без ``auto_transfer_next`` передачи не будет вовсе.

Числа SQL на этом кейсе измерены **отдельно** (96 → 97 при батчинге, ответ
идентичен, батчинг откачен) — см. ``docs/night/logs/measure_300_*.json`` и
``docs/night/tickets/T-300-auto-transfer-batching.md``. Здесь измерений нет:
тест проверяет результат и ничего не пишет на диск.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.transfer import Transfer
from app.models.work_task import WorkTask
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    SECTION_TYPE_RAW_STOCK,
)
from sqlalchemy import select

from tests.helpers.completed_operations import build_operation_route
from tests.helpers.transfers_chain import seed_manual_in
from tests.stock.helpers import record_transfer_receive
from tests.test_integrity_invariants import (
    _make_user,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)

pytestmark = pytest.mark.asyncio


async def _prepare(session, *, sku: str) -> tuple[dict, object, object, WorkTask]:
    """Цепочка RAW → P1 → P2 с материалом на первом участке."""
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
    raw, _p1, p2 = fx["sections"]
    # Разные СПГ — обязательное условие цикла: build_operation_route кладёт все
    # участки в один СПГ, и sections_share_spg рвёт авто-передачу на первом шаге.
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
    p1_task = await _first_task(session, _p1)
    # Приём заводит issued_quantity задания и кладёт остаток в ops-группе
    # «до своего этапа», откуда его возьмёт TRANSFER_SEND. Подпись — по этапу
    # ИСТОЧНИКА: она описывает, что уходит, а не что приходит (ADR-0055).
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=raw.id,
        to_location_id=_p1.id,
        quantity=Decimal(100),
        task_id=p1_task.id,
        created_by=user.id,
        completed_operations=ops_raw,
    )
    return fx, user, p1_task, p2


async def _first_task(session, section) -> WorkTask:
    task = (
        (await session.execute(select(WorkTask).where(WorkTask.section_id == section.id)))
        .scalars()
        .first()
    )
    assert task is not None, "на производственном участке должно быть задание"
    return task


@pytest.mark.asyncio
async def test_complete_creates_auto_transfer_to_next_group(session) -> None:
    """Завершение задания переносит факт на участок следующего СПГ."""
    from app.services.shopfloor.operations_tasks import complete_task

    _fx, user, p1_task, p2_section = await _prepare(session, sku="T300")
    await complete_task(
        session,
        task_id=p1_task.id,
        good_quantity=Decimal(100),
        defect_quantity=Decimal(0),
        actor_id=user.id,
        comment="авто-передача",
        auto_transfer_next=True,
    )

    transfers = (
        (await session.execute(select(Transfer).order_by(Transfer.id))).scalars().all()
    )
    assert len(transfers) == 1, f"ожидалась одна авто-передача, создано {len(transfers)}"
    transfer = transfers[0]
    assert transfer.from_task_id == p1_task.id
    assert transfer.to_task_id is not None, "у авто-передачи есть получатель"
    receiving = await session.get(WorkTask, transfer.to_task_id)
    assert receiving is not None and receiving.section_id == p2_section.id, (
        "факт ушёл не на участок СПГ-2"
    )
    assert transfer.sent_quantity == Decimal(100)
    assert getattr(transfer.status, "value", transfer.status) == "accepted"
    assert transfer.rejected_quantity is None

    await assert_no_invariants_violations(session, context="T300")
    await assert_no_stock_ledger_invariants_violations(session, context="T300")


@pytest.mark.asyncio
async def test_completed_task_does_not_double_transfer_on_replay(session) -> None:
    """Повторное завершение не создаёт вторую передачу на тот же факт.

    Идемпотентность авто-передачи: тот же `idempotency_key` на втором
    `complete_task` не должен удваивать движение в ledger'е.
    """
    from app.services.shopfloor.operations_tasks import complete_task

    _fx, user, p1_task, _p2 = await _prepare(session, sku="T300IDEM")
    payload = {
        "task_id": p1_task.id,
        "good_quantity": Decimal(100),
        "defect_quantity": Decimal(0),
        "actor_id": user.id,
        "idempotency_key": "t300-idem",
        "auto_transfer_next": True,
    }
    await complete_task(session, **payload)
    await complete_task(session, **payload)

    transfers = (
        (await session.execute(select(Transfer).order_by(Transfer.id))).scalars().all()
    )
    assert len(transfers) == 1, (
        f"повторное завершение создало {len(transfers)} передач вместо одной"
    )

    await assert_no_invariants_violations(session, context="T300IDEM")
    await assert_no_stock_ledger_invariants_violations(session, context="T300IDEM")
