"""#300/#307: авто-передача при завершении задачи — поведение и бюджет SQL.

Завершение задания на производственном участке переносит факт на следующий
участок ДРУГОГО СПГ: создаётся передача, факт уходит, ledger сходится.

Тест ловит все условия выхода цикла
``auto_create_transfer_after_complete``: без разнесённых по СПГ участков
(``sections_share_spg`` рвёт цикл), без приёма на участок
(``issued_quantity``) и без ``auto_transfer_next`` передачи не будет вовсе.

#307 достроил случай, которого не хватало #300: длинная цепочка
``P1 → W1 → W2 → P2`` (три перехода, два транзитных хопа). На ней цикл
действительно разворачивается, поэтому батчинг (снимок строк/этапов/СПГ/
задач одним проходом) окупается: SELECT'ов цикла 22 → 7, весь
``complete_task`` 224 → 209. На короткой цепочке из #300 снимок стоит
одного лишнего SELECT'а (96 → 97) — это осознанная цена фиксированного
прохода. Числа и вердикт — ``docs/night/tickets/T-307-auto-transfer-long-chain.md``.
Замер воспроизводится тестом ``test_long_chain_sql_budget`` с ``-s``
(печатает метрики, на диск ничего не пишет).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.models.internal_plan import SectionPlanLine
from app.models.route import RouteStage
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    SECTION_TYPE_RAW_STOCK,
    SECTION_TYPE_WIP_STOCK,
)
from app.stock.models import Reason, StockTransaction
from sqlalchemy import select

from tests.helpers.completed_operations import (
    build_operation_route,
    register_section_operations,
)
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


async def _prepare_long_chain(session, *, sku: str) -> dict:
    """RAW → P1 → W1 → W2 → P2: три перехода, два из них транзитные.

    Цикл ``auto_create_transfer_after_complete`` продолжается только через
    транзитные этапы (после первого производственного — ``break``), поэтому
    длинная цепочка строится складами-хопами: ``P1 → W1 → W2 → P2``.
    Каждый соседний участок — в своём СПГ, иначе ``sections_share_spg``
    рвёт цепочку на первом же шаге.

    План-строки и задания строит ``build_operation_route`` для RAW/P1;
    транзитные этапы и финальный цех добавляются сюда же. ``release_batch``
    не вызывается: он создал бы второй комплект строк на ту же позицию, и
    поиск «следующей строки по sequence» пошёл бы не по той цепочке.
    """
    fx = await build_operation_route(
        session,
        sku=sku,
        qty=Decimal(100),
        stages=[
            (f"{sku}-RAW", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            (f"{sku}-P1", SECTION_TYPE_PRODUCTION, ["P1_OP"]),
        ],
    )
    raw, p1 = fx["sections"]
    route, product, plan = fx["route"], fx["product"], fx["plan"]
    internal_plan_id = fx["plan_lines"][0].internal_plan_id
    p1_task = fx["tasks"][1]

    w1 = Section(
        code=f"{sku}-W1", name=f"{sku}-W1", type=SECTION_TYPE_WIP_STOCK,
        is_active=True, sort_order=3,
    )
    w2 = Section(
        code=f"{sku}-W2", name=f"{sku}-W2", type=SECTION_TYPE_WIP_STOCK,
        is_active=True, sort_order=4,
    )
    p2 = Section(
        code=f"{sku}-P2", name=f"{sku}-P2", type=SECTION_TYPE_PRODUCTION,
        is_active=True, sort_order=5,
    )
    session.add_all([w1, w2, p2])
    await session.flush()
    await register_section_operations(session, p2.id, ["P2_OP"])

    # P1 остаётся в СПГ по умолчанию (вместе с RAW); хопы и P2 — в своих.
    for section, suffix in ((w1, "W1"), (w2, "W2"), (p2, "P2")):
        spg = StorageProductionGroup(
            code=f"{sku}-SPG-{suffix}", name=f"СПГ {suffix}",
            is_active=True, sort_order=1,
        )
        session.add(spg)
        await session.flush()
        session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))
    await session.flush()

    transit_w1 = RouteStage(
        route_id=route.id, sequence=3, section_id=None,
        stage_kind="transit", storage_section_id=w1.id, is_final=False,
    )
    transit_w2 = RouteStage(
        route_id=route.id, sequence=4, section_id=None,
        stage_kind="transit", storage_section_id=w2.id, is_final=False,
    )
    final_p2 = RouteStage(
        route_id=route.id, sequence=5, section_id=p2.id, is_final=True,
    )
    session.add_all([transit_w1, transit_w2, final_p2])
    await session.flush()

    lines: list[SectionPlanLine] = []
    for section, stage, sequence in (
        (w1, transit_w1, 3), (w2, transit_w2, 4), (p2, final_p2, 5),
    ):
        line = SectionPlanLine(
            internal_plan_id=internal_plan_id,
            plan_position_id=fx["position"].id,
            section_id=section.id,
            product_id=product.id,
            route_id=route.id,
            route_stage_id=stage.id,
            sequence=sequence,
            planned_quantity=Decimal(100),
        )
        session.add(line)
        await session.flush()
        lines.append(line)

    # Задание финального участка ждёт материал, как после выпуска плана.
    p2_task = WorkTask(
        section_plan_line_id=lines[2].id,
        section_id=p2.id,
        product_id=product.id,
        route_stage_id=final_p2.id,
        planned_quantity=Decimal(100),
        status=WorkTaskStatus.waiting_previous,
        due_date=plan.period_end,
    )
    session.add(p2_task)
    await session.flush()

    user = await _make_user(session, f"{sku.lower()}@local")
    ops_raw = await completed_operations_through_stage(
        session, route_id=route.id, through_sequence=1
    )
    await seed_manual_in(
        session,
        user_id=user.id,
        location_id=raw.id,
        product_id=product.id,
        quantity=Decimal(100),
        completed_operations=ops_raw,
    )
    # Приём заводит issued_quantity задания P1; подпись — по этапу источника.
    await record_transfer_receive(
        session,
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=p1.id,
        quantity=Decimal(100),
        task_id=p1_task.id,
        created_by=user.id,
        completed_operations=ops_raw,
    )
    return {
        "user": user,
        "product": product,
        "p1_task": p1_task,
        "p2_task": p2_task,
        "sections": {"raw": raw, "p1": p1, "w1": w1, "w2": w2, "p2": p2},
    }


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


@pytest.mark.asyncio
async def test_section_in_two_spgs_shares_any_membership(session) -> None:
    """Участок в двух СПГ: общий СПГ определяется пересечением членств (#307).

    ``uq_spg_sections`` уникален по паре (СПГ, участок), поэтому участок
    может состоять в нескольких группах. Если следующий участок делит с ним
    хотя бы одну, авто-передача не создаётся. Точечное чтение брало
    произвольную строку членства; снимок отвечает по факту.
    """
    from app.services.shopfloor.operations_tasks import complete_task

    _fx, user, p1_task, p2_section = await _prepare(session, sku="T307MULTI")
    p2_link = await session.scalar(
        select(SpgSection).where(SpgSection.section_id == p2_section.id)
    )
    assert p2_link is not None
    session.add(
        SpgSection(
            spg_id=p2_link.spg_id,
            section_id=p1_task.section_id,
            sort_order=0,
        )
    )
    await session.flush()

    await complete_task(
        session,
        task_id=p1_task.id,
        good_quantity=Decimal(100),
        defect_quantity=Decimal(0),
        actor_id=user.id,
        comment="участки делят второй СПГ",
        auto_transfer_next=True,
    )

    transfers = (
        (await session.execute(select(Transfer).order_by(Transfer.id))).scalars().all()
    )
    assert transfers == [], "общий СПГ (хотя бы один) должен останавливать авто-передачу"

    await assert_no_invariants_violations(session, context="T307MULTI")
    await assert_no_stock_ledger_invariants_violations(session, context="T307MULTI")


@pytest.mark.asyncio
async def test_long_chain_creates_three_transfers(session) -> None:
    """P1 → W1 → W2 → P2: авто-передача проходит по всей длинной цепочке."""
    from app.services.shopfloor.operations_tasks import complete_task

    fx = await _prepare_long_chain(session, sku="T307LONG")
    await complete_task(
        session,
        task_id=fx["p1_task"].id,
        good_quantity=Decimal(100),
        defect_quantity=Decimal(0),
        actor_id=fx["user"].id,
        comment="авто-передача по цепочке",
        auto_transfer_next=True,
    )

    transfers = (
        (await session.execute(select(Transfer).order_by(Transfer.id))).scalars().all()
    )
    assert len(transfers) == 3, f"ожидались три передачи цепочки, создано {len(transfers)}"
    sections = fx["sections"]
    assert [t.from_section_id for t in transfers] == [
        sections["p1"].id,
        sections["w1"].id,
        sections["w2"].id,
    ]
    assert [t.to_section_id for t in transfers] == [
        sections["w1"].id,
        sections["w2"].id,
        sections["p2"].id,
    ]
    assert all(t.sent_quantity == Decimal(100) for t in transfers)
    assert all(t.dimensions is None for t in transfers)
    assert all(getattr(t.status, "value", t.status) == "accepted" for t in transfers)

    # Каждая передача — пара проводок ledger: SEND с задачи-источника и
    # RECEIVE на задачу-получателя. Причина — часть контракта, её не
    # переписывает ни один шаг цепочки.
    transactions = (
        (
            await session.execute(
                select(StockTransaction).where(
                    StockTransaction.transfer_id.in_([t.id for t in transfers])
                )
            )
        )
        .scalars()
        .all()
    )
    reasons_by_transfer: dict[int, set[Reason]] = {}
    for transaction in transactions:
        reasons_by_transfer.setdefault(transaction.transfer_id, set()).add(
            transaction.reason
        )
    assert reasons_by_transfer == {
        transfer.id: {Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE}
        for transfer in transfers
    }

    await assert_no_invariants_violations(session, context="T307LONG")
    await assert_no_stock_ledger_invariants_violations(session, context="T307LONG")


def _kinds(statements: list[str]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    for statement in statements:
        verb = statement.split(" ", 1)[0].upper()
        kinds[verb] = kinds.get(verb, 0) + 1
    return kinds


async def _measure_completion(session, monkeypatch, fx: dict) -> dict:
    """Замер ``complete_task`` с авто-передачей: цикл и ``transfer_send`` отдельно.

    Слушатель ``before_cursor_execute`` на engine; внутренние вызовы
    ``transfer_send`` помечены вложенным счётчиком, поэтому SQL цикла
    (снимок цепочки, поиск задач, flush проекции) считается без SQL самих
    передач. Транзакция теста откатывается фикстурой ``session``.
    """
    from time import perf_counter

    from app.services.shopfloor.operations_tasks import complete_task
    from app.transfers import services as transfers_services
    from sqlalchemy import event

    statements: list[str] = []
    phases: dict[str, list[str]] = {"loop": [], "send": []}
    send_calls = 0
    helper_depth = 0
    send_depth = 0
    engine = session.bind.sync_engine

    def _before(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split())
        statements.append(normalized)
        if send_depth:
            phases["send"].append(normalized)
        elif helper_depth:
            phases["loop"].append(normalized)

    original_send = transfers_services.transfer_send
    original_helper = transfers_services.auto_create_transfer_after_complete

    async def counted_send(*args, **kwargs):
        nonlocal send_calls, send_depth
        send_calls += 1
        send_depth += 1
        try:
            return await original_send(*args, **kwargs)
        finally:
            send_depth -= 1

    async def counted_helper(*args, **kwargs):
        nonlocal helper_depth
        helper_depth += 1
        try:
            return await original_helper(*args, **kwargs)
        finally:
            helper_depth -= 1

    monkeypatch.setattr(transfers_services, "transfer_send", counted_send)
    monkeypatch.setattr(
        transfers_services, "auto_create_transfer_after_complete", counted_helper
    )

    event.listen(engine, "before_cursor_execute", _before)
    try:
        base = len(statements)
        started = perf_counter()
        response = await complete_task(
            session,
            task_id=fx["p1_task"].id,
            good_quantity=Decimal(100),
            defect_quantity=Decimal(0),
            actor_id=fx["user"].id,
            comment="замер",
            auto_transfer_next=True,
        )
        elapsed_ms = (perf_counter() - started) * 1000
        total = len(statements) - base
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    loop = phases["loop"]
    send = phases["send"]
    return {
        "total": total,
        "kinds": _kinds(statements),
        "loop": len(loop),
        "loop_kinds": _kinds(loop),
        "send": len(send),
        "send_kinds": _kinds(send),
        "send_calls": send_calls,
        "time_total_ms": elapsed_ms,
        "response": {
            "task_id": response["task_id"],
            "status": response["status"],
            "completed_quantity": str(response["completed_quantity"]),
            "transactions": len(response["transaction_ids"]),
        },
        # Полный ответ — для сверки «до/после» по рецепту docs/testing-guide.md
        # (json.dumps(..., sort_keys=True, default=str)).
        "response_full": json.dumps(response, sort_keys=True, default=str),
    }


@pytest.mark.asyncio
async def test_long_chain_sql_budget(session, monkeypatch) -> None:
    """Бюджет SQL цикла авто-передачи: снимок цепочки, а не O(steps) чтений (#307)."""
    fx = await _prepare_long_chain(session, sku="T307SQL")
    await session.flush()

    metrics = await _measure_completion(session, monkeypatch, fx)
    print("MEASURE307", metrics)

    assert metrics["send_calls"] == 3
    # Три перехода. До батчинга цикл стоил 22 SELECT (по ~7 на шаг); после —
    # фиксированный снимок: строки позиции, этапы (+selectin операций), СПГ,
    # открытые задачи и два db.get созданных транзитных задач. UPDATE —
    # flush кэша строки плана из write-path, читающих запросов он не добавляет.
    # Нижняя граница ловит поломку атрибуции фаз (иначе «0 ≤ 8» пройдёт).
    assert 5 <= metrics["loop_kinds"].get("SELECT", 0) <= 8, metrics
    assert 6 <= metrics["loop"] <= 10, metrics
    # Ответ не зависит от формы чтения цепочки: та же задача, тот же факт.
    assert metrics["response"] == {
        "task_id": fx["p1_task"].id,
        "status": "completed",
        "completed_quantity": "100",
        "transactions": 2,
    }, metrics


@pytest.mark.asyncio
async def test_short_chain_sql_budget(session, monkeypatch) -> None:
    """Короткая цепочка (#300): снимок стоит одного лишнего SELECT.

    Границы — не «число ради числа»: верхняя не даёт вернуться пошаговым
    чтениям, нижняя ловит поломку атрибуции фаз (иначе «0 ≤ 6» пройдёт).
    """
    _fx, user, p1_task, _p2 = await _prepare(session, sku="T307SHORT")
    await session.flush()

    metrics = await _measure_completion(
        session, monkeypatch, {"p1_task": p1_task, "user": user}
    )
    print("MEASURE307SHORT", metrics)

    assert metrics["send_calls"] == 1
    assert 4 <= metrics["loop_kinds"].get("SELECT", 0) <= 6, metrics
    assert 5 <= metrics["loop"] <= 7, metrics
    assert metrics["response"] == {
        "task_id": p1_task.id,
        "status": "completed",
        "completed_quantity": "100",
        "transactions": 2,
    }, metrics
