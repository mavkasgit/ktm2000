"""ADR-0043 / #207: признак «пройденные операции» на всех путях записи ledger.

Каждый путь записи домена (передача, завершение, брак/решение по дефекту,
возврат остатка, трансформация, откат/amend) обязан записать в
``StockTransaction.completed_operations`` ровно тот список ``operation_code``,
который материал реально прошёл: для обычного этапа — операции своего этапа
включительно, для «материал уходит назад» (возврат остатка, ``return_previous``,
вход трансформации) — операции до ПРЕДЫДУЩЕГО этапа.

Маршрут позиции — единственный источник признака (ADR-0021): по остаткам
на складе «сырьё» и «подготовленное сырьё» неразличимы.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action
from app.models.defect import DefectDecisionType
from app.models.section import Section
from app.models.work_task import WorkTask
from app.reversal.service import reversal_service
from app.services.plan_generation import create_release_batch, release_batch
from app.services.route_storage_classifier import (
    SECTION_TYPE_FINISHED_STOCK,
    SECTION_TYPE_PRODUCTION,
    SECTION_TYPE_RAW_STOCK,
    SECTION_TYPE_WIP_STOCK,
)
from app.services.shopfloor.operations_defects import create_defect, defect_decide
from app.services.shopfloor.operations_tasks import complete_task, final_release
from app.stock import (
    Reason,
    StockCommand,
    StockCommandService,
    StockTransaction,
)
from app.transfers.services import transfer_send
from tests.helpers.completed_operations import build_operation_route, ops_through
from tests.stock.helpers import (
    FAKE_DEFECT_DECISION_MAP,
    FAKE_SCRAP_POLICY,
    record_transfer_receive,
)
from tests.test_integrity_invariants import _auth_headers, assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


# Маршрут №3 (ЮП-460) из тикета #207: сырьё → пресс → дробеструй → склад
# подготовки → финальная сборка. Признак материала на «Складе подготовки»
# обязан быть полным (все пять кодов), на «Складе сырья» — только ISSUE_RAW.
YP460_STAGES: list[tuple[str, str, list[str]]] = [
    ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
    ("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB", "PRESS_WINDOW"]),
    ("Дробеструй", SECTION_TYPE_PRODUCTION, ["SHOT"]),
    ("Склад подготовки", SECTION_TYPE_WIP_STOCK, ["MOVE_TO_PREP_STOCK"]),
    ("Финальная сборка", SECTION_TYPE_PRODUCTION, ["ASSEMBLY"]),
]

# Трёхэтапный маршрут для заданий: последний этап отличается от предыдущего
# набором кодов, поэтому «признак своего этапа» и «признак до предыдущего
# этапа» — разные списки, и подмена одного другим тестом ловится.
TASK_STAGES: list[tuple[str, str, list[str]]] = [
    ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
    ("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB", "PRESS_WINDOW"]),
    ("Дробеструй", SECTION_TYPE_PRODUCTION, ["SHOT"]),
]

SAW_STAGES: list[tuple[str, str, list[str]]] = [
    ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
    ("Пила", SECTION_TYPE_PRODUCTION, ["SAW"]),
    ("Упаковка", SECTION_TYPE_PRODUCTION, ["PACK"]),
]

DIMS_IN = {"length_mm": 2700}
SAW_OUTPUTS = [
    {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
    {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
]


# ─── helpers ────────────────────────────────────────────────────────────────


async def _txs(session: AsyncSession, **filters) -> list[StockTransaction]:
    stmt = select(StockTransaction).order_by(StockTransaction.id.asc())
    for name, value in filters.items():
        stmt = stmt.where(getattr(StockTransaction, name) == value)
    return list((await session.execute(stmt)).scalars().all())


async def _only_tx(
    session: AsyncSession, *, reason: Reason, **filters
) -> StockTransaction:
    """Ровно одна проводка данного reason — иначе тест проверяет не то."""
    found = await _txs(session, reason=reason, **filters)
    assert len(found) == 1, f"ожидалась одна проводка {reason}, получено {len(found)}"
    return found[0]


async def _seed_balance(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
    location_id: int,
    qty: Decimal,
    dimensions: dict | None = None,
) -> None:
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            dimensions=dimensions,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _issue_to_task(
    session: AsyncSession, fx: dict, task: WorkTask, *, qty: Decimal
) -> None:
    """Выдать материал на задание: приход на склад + TRANSFER_RECEIVE на этап."""
    raw = fx["sections"][0]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=qty,
    )
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=raw.id,
        to_location_id=task.section_id,
        quantity=qty,
        task_id=task.id,
        created_by=fx["user"].id,
    )
    await session.commit()


async def _open_defect(
    session: AsyncSession, fx: dict, task: WorkTask, *, qty: Decimal
) -> int:
    created = await create_defect(
        session,
        task_id=task.id,
        quantity=qty,
        actor_id=fx["user"].id,
        reason="brak",
        comment="дефект для регрессии #207",
    )
    await session.commit()
    return created["defect_id"]


async def _transfer_action(
    session: AsyncSession, transfer_id: int
) -> Action:
    action = await session.scalar(
        select(Action).where(
            Action.action_type == "transfer_send",
            Action.ref_id == transfer_id,
            Action.status == "active",
        )
    )
    assert action is not None, "transfer_send не записал действие в журнал"
    return action


async def _compensations_of(
    session: AsyncSession, source_tx_ids: list[int]
) -> list[StockTransaction]:
    stmt = (
        select(StockTransaction)
        .where(StockTransaction.reverses_id.in_(source_tx_ids))
        .order_by(StockTransaction.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ─── ЮП-460:acceptance-случай тикета #207 ───────────────────────────────────


async def test_transfer_out_of_prep_stock_carries_all_route_operations(
    session: AsyncSession,
) -> None:
    """Передача с «Склада подготовки» несёт все пять кодов маршрута.

    Материал, дошедший до склада подготовки, прошёл ISSUE_RAW, обе
    прессовые операции, дробеструй и MOVE_TO_PREP_STOCK. Приёмная задача
    (финальная сборка) ещё не касалась материала, поэтому TRANSFER_RECEIVE
    несёт признак ИСХОДНОГО задания — пять кодов, а не шесть.
    """
    fx = await build_operation_route(session, sku="YP460P", stages=YP460_STAGES)
    prep, assembly = fx["tasks"][3], fx["tasks"][4]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=prep.section_id,
        qty=Decimal("100"),
    )

    result = await transfer_send(
        session,
        from_task_id=prep.id,
        to_task_id=assembly.id,
        quantity=Decimal("10"),
        actor_id=fx["user"].id,
        allow_over_plan=True,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="yp460-prep-stock")

    expected = [
        "ISSUE_RAW",
        "MOVE_TO_PREP_STOCK",
        "PRESS_COMB",
        "PRESS_WINDOW",
        "SHOT",
    ]
    assert result["transfer_id"] is not None
    send_tx = await _only_tx(session, reason=Reason.TRANSFER_SEND, transfer_id=result["transfer_id"])
    receive_tx = await _only_tx(session, reason=Reason.TRANSFER_RECEIVE, transfer_id=result["transfer_id"])
    assert send_tx.completed_operations == expected
    assert receive_tx.completed_operations == expected


async def test_transfer_out_of_raw_stock_carries_only_issue_raw(
    session: AsyncSession,
) -> None:
    """Передача с «Склада сырья» несёт только ISSUE_RAW.

    Второй полюс acceptance-кейса: то же сырьё, снятое до пресса, не должно
    выглядеть в ledger как подготовленное.
    """
    fx = await build_operation_route(session, sku="YP460R", stages=YP460_STAGES)
    raw, press = fx["tasks"][0], fx["tasks"][1]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=raw.section_id,
        qty=Decimal("100"),
    )

    result = await transfer_send(
        session,
        from_task_id=raw.id,
        to_task_id=press.id,
        quantity=Decimal("10"),
        actor_id=fx["user"].id,
        allow_over_plan=True,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="yp460-raw-stock")

    assert result["transfer_id"] is not None
    send_tx = await _only_tx(session, reason=Reason.TRANSFER_SEND, transfer_id=result["transfer_id"])
    receive_tx = await _only_tx(session, reason=Reason.TRANSFER_RECEIVE, transfer_id=result["transfer_id"])
    assert send_tx.completed_operations == ["ISSUE_RAW"]
    assert receive_tx.completed_operations == ["ISSUE_RAW"]


# ─── complete_task ───────────────────────────────────────────────────────────


async def test_complete_task_good_and_scrap_carry_task_stage_operations(
    session: AsyncSession,
) -> None:
    """COMPLETE и SCRAP одного завершения несут операции этапа задания."""
    fx = await build_operation_route(session, sku="COPTASK", stages=TASK_STAGES)
    press = fx["tasks"][1]
    await _issue_to_task(session, fx, press, qty=Decimal("100"))

    result = await complete_task(
        session,
        task_id=press.id,
        good_quantity=Decimal("7"),
        defect_quantity=Decimal("3"),
        actor_id=fx["user"].id,
        defect_reason="brak",
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="complete-task-ops")

    expected = ops_through(TASK_STAGES, 2)
    assert expected == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW"]
    complete_tx = await _only_tx(session, reason=Reason.COMPLETE, task_id=press.id)
    scrap_tx = await _only_tx(session, reason=Reason.SCRAP, task_id=press.id)
    assert complete_tx.completed_operations == expected
    assert scrap_tx.completed_operations == expected
    assert result["defect_id"] is not None


# ─── defect_decide ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("decision", "expected_codes"),
    [
        (DefectDecisionType.scrap, ops_through(TASK_STAGES, 3)),
        (DefectDecisionType.rework_current, ops_through(TASK_STAGES, 3)),
        (DefectDecisionType.accept_with_deviation, ops_through(TASK_STAGES, 3)),
        # Возврат НАЗАД по маршруту: материал теряет операции своего этапа.
        (DefectDecisionType.return_previous, ops_through(TASK_STAGES, 2)),
    ],
    ids=["scrap", "rework_current", "accept_with_deviation", "return_previous"],
)
async def test_defect_decide_carries_expected_operations(
    session: AsyncSession,
    decision: DefectDecisionType,
    expected_codes: list[str],
) -> None:
    """Решение по дефекту записывает признак по направлению движения материала."""
    fx = await build_operation_route(session, sku=f"DEF{decision.value.upper()}", stages=TASK_STAGES)
    shot = fx["tasks"][2]
    await _issue_to_task(session, fx, shot, qty=Decimal("100"))
    defect_id = await _open_defect(session, fx, shot, qty=Decimal("5"))

    await defect_decide(
        session,
        defect_id=defect_id,
        decision_type=decision,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        idempotency_key=f"k-{decision.value}",
        defect_decision_map=FAKE_DEFECT_DECISION_MAP,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context=f"defect-{decision.value}")

    from app.models.defect import Defect

    defect = await session.get(Defect, defect_id)
    assert defect is not None and defect.stock_transaction_id is not None
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.completed_operations == expected_codes
    if decision is DefectDecisionType.return_previous:
        # Признак «до предыдущего этапа» не равен признаку своего этапа —
        # иначе тест проходил бы и при подмене одного другим.
        assert expected_codes != ops_through(TASK_STAGES, 3)


# ─── return_remainder ───────────────────────────────────────────────────────


async def test_return_remainder_carries_previous_stage_operations(
    session: AsyncSession, client
) -> None:
    """Возврат необработанного остатка несёт операции до ПРЕДЫДУЩЕГО этапа.

    Остаток с участка «Дробеструй» уходит на склад необработанным, поэтому
    признак ограничен прессом, а не включает SHOT.
    """
    fx = await build_operation_route(session, sku="RETREM", stages=TASK_STAGES)
    shot = fx["tasks"][2]
    await _issue_to_task(session, fx, shot, qty=Decimal("100"))

    resp = await client.post(
        "/api/shopfloor/remainders/return",
        json={"task_id": shot.id, "quantity": "10", "comment": "остаток"},
        headers=_auth_headers(fx["user"]),
    )
    assert resp.status_code == 200, resp.text
    await session.commit()
    await assert_no_invariants_violations(session, context="return-remainder-ops")

    tx = await _only_tx(session, reason=Reason.RETURN_TO_STOCK, task_id=shot.id)
    assert tx.completed_operations == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW"]
    assert tx.completed_operations != ops_through(TASK_STAGES, 3)


# ─── трансформация ──────────────────────────────────────────────────────────


async def test_transform_consume_and_outputs_carry_stage_appropriate_operations(
    session: AsyncSession,
) -> None:
    """Вход трансформации несёт признак ДО этапа, выходы — ВКЛЮЧАЯ его.

    Списание заготовок — материал, который до пилы ещё не проходил SAW;
    приход выходов — материал, который уже прошёл. Одна и та же порция
    факта пишет два разных значения в одном действии.
    """
    fx = await build_operation_route(
        session,
        sku="TRFMOPS",
        stages=SAW_STAGES,
        transform_at=2,
        input_quantity=Decimal("100"),
        input_dimensions=dict(DIMS_IN),
        outputs=SAW_OUTPUTS,
    )
    saw = fx["tasks"][1]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=saw.section_id,
        qty=Decimal("100"),
        dimensions=dict(DIMS_IN),
    )

    await complete_task(
        session,
        task_id=saw.id,
        good_quantity=Decimal("100"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="transform-ops")

    consume_tx = await _only_tx(session, reason=Reason.TRANSFORM_CONSUME, task_id=saw.id)
    assert consume_tx.completed_operations == ["ISSUE_RAW"]

    output_txs = await _txs(session, reason=Reason.COMPLETE, task_id=saw.id)
    assert len(output_txs) == 2, "спецификация пила даёт два выхода"
    for out_tx in output_txs:
        assert out_tx.completed_operations == ["ISSUE_RAW", "SAW"]


# ─── откат и amend ───────────────────────────────────────────────────────────


async def test_reverse_transfer_send_mirrors_completed_operations(
    session: AsyncSession,
) -> None:
    """Компенсации передачи несут ровно признак исходных проводок.

    Откат возвращает «тот же материал»: если бы компенсация обнулила
    признак, отказанная передача оставила бы на складе материал без
    истории операций.
    """
    fx = await build_operation_route(session, sku="REVTX", stages=YP460_STAGES)
    prep, assembly = fx["tasks"][3], fx["tasks"][4]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=prep.section_id,
        qty=Decimal("100"),
    )
    result = await transfer_send(
        session,
        from_task_id=prep.id,
        to_task_id=assembly.id,
        quantity=Decimal("10"),
        actor_id=fx["user"].id,
        allow_over_plan=True,
    )
    await session.commit()
    transfer_id = result["transfer_id"]
    assert transfer_id is not None

    sources = await _txs(session, transfer_id=transfer_id)
    assert len(sources) == 2
    action = await _transfer_action(session, transfer_id)

    preview = await reversal_service.preview_reverse(session, action.id)
    assert preview.plan_token is not None and preview.blockers == []
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, reason="тест #207",
        actor_id=fx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="reverse-transfer-ops")

    comps = await _compensations_of(session, [tx.id for tx in sources])
    assert len(comps) == 2
    for comp in comps:
        source = next(tx for tx in sources if tx.id == comp.reverses_id)
        assert comp.completed_operations == source.completed_operations
        assert comp.completed_operations == [
            "ISSUE_RAW",
            "MOVE_TO_PREP_STOCK",
            "PRESS_COMB",
            "PRESS_WINDOW",
            "SHOT",
        ]


async def test_amend_transfer_send_mirrors_completed_operations(
    session: AsyncSession,
) -> None:
    """Компенсация amend'а старой передачи зеркалит её признак."""
    fx = await build_operation_route(session, sku="AMDTX", stages=YP460_STAGES)
    prep, assembly = fx["tasks"][3], fx["tasks"][4]
    await _seed_balance(
        session,
        user_id=fx["user"].id,
        product_id=fx["product"].id,
        location_id=prep.section_id,
        qty=Decimal("100"),
    )
    result = await transfer_send(
        session,
        from_task_id=prep.id,
        to_task_id=assembly.id,
        quantity=Decimal("10"),
        actor_id=fx["user"].id,
        allow_over_plan=True,
    )
    await session.commit()
    transfer_id = result["transfer_id"]
    assert transfer_id is not None
    sources = await _txs(session, transfer_id=transfer_id)
    assert len(sources) == 2
    action = await _transfer_action(session, transfer_id)

    changes = {"quantity": "3"}
    preview = await reversal_service.preview_amend(session, action.id, changes)
    assert preview.plan_token is not None and preview.blockers == []
    amended = await reversal_service.amend(
        session,
        action.id,
        changes=changes,
        plan_token=preview.plan_token,
        reason="оператор ошибся количеством",
        actor="Тест",
        actor_id=fx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="amend-transfer-ops")

    comps = await _compensations_of(session, [tx.id for tx in sources])
    assert len(comps) == 2
    for comp in comps:
        source = next(tx for tx in sources if tx.id == comp.reverses_id)
        assert comp.completed_operations == source.completed_operations

    # Новая пара проводок (после amend) несёт тот же признак: количество
    # изменилось, пройденные операции материала — нет.
    new_transfer_id = amended.new_ref_id
    assert new_transfer_id is not None
    new_txs = await _txs(session, transfer_id=new_transfer_id)
    assert len(new_txs) == 2
    for tx in new_txs:
        assert tx.completed_operations == [
            "ISSUE_RAW",
            "MOVE_TO_PREP_STOCK",
            "PRESS_COMB",
            "PRESS_WINDOW",
            "SHOT",
        ]


async def test_reverse_task_complete_mirrors_completed_operations(
    session: AsyncSession,
) -> None:
    """Компенсация task_complete зеркалит признак выпуска."""
    fx = await build_operation_route(session, sku="REVCOMP", stages=TASK_STAGES)
    press = fx["tasks"][1]
    await _issue_to_task(session, fx, press, qty=Decimal("100"))
    await complete_task(
        session,
        task_id=press.id,
        good_quantity=Decimal("10"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()

    sources = await _txs(session, reason=Reason.COMPLETE, task_id=press.id)
    assert len(sources) == 1
    action = await session.scalar(
        select(Action).where(
            Action.action_type == "task_complete",
            Action.ref_id == press.id,
            Action.status == "active",
        )
    )
    assert action is not None

    preview = await reversal_service.preview_reverse(session, action.id)
    assert preview.plan_token is not None and preview.blockers == []
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, reason="тест #207",
        actor_id=fx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="reverse-complete-ops")

    comps = await _compensations_of(session, [tx.id for tx in sources])
    assert len(comps) == 1
    assert comps[0].completed_operations == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW"]


# ─── сквозной инвариант: плановая проводка не остаётся NULL ─────────────────


async def test_plan_driven_writes_never_store_null_completed_operations(
    session: AsyncSession,
) -> None:
    """Ни одна плановная проводка (с ``task_id``) не остаётся без признака.

    NULL в ledger означает «состояние неизвестно, запись вне маршрута».
    Плановая проводка, потерявшая признак, сделала бы это значение
    двусмысленным ровно в середине маршрута.

    Сценарий намеренно накрывает ВСЕ плановые пути записи: передача
    (SEND/RECEIVE), завершение (COMPLETE/SCRAP) и финальный выпуск
    на маршруте с заданиями, плюс автозавершение этапа при выпуске
    партии (``release_batch``) на отдельной позиции.
    """
    output_stock = Section(
        code="NOINVN-FG",
        name="Склад ГП",
        type=SECTION_TYPE_FINISHED_STOCK,
        is_active=True,
        sort_order=90,
        is_output_default=True,
    )
    session.add(output_stock)
    await session.flush()
    fx = await build_operation_route(session, sku="NOINVN", stages=TASK_STAGES)
    press, shot = fx["tasks"][1], fx["tasks"][2]
    await _issue_to_task(session, fx, press, qty=Decimal("100"))
    await complete_task(
        session,
        task_id=press.id,
        good_quantity=Decimal("10"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await transfer_send(
        session,
        from_task_id=press.id,
        to_task_id=shot.id,
        quantity=Decimal("5"),
        actor_id=fx["user"].id,
        allow_over_plan=True,
    )
    await _issue_to_task(session, fx, shot, qty=Decimal("5"))
    await complete_task(
        session,
        task_id=shot.id,
        good_quantity=Decimal("3"),
        defect_quantity=Decimal("2"),
        actor_id=fx["user"].id,
        defect_reason="brak",
        **FAKE_SCRAP_POLICY,
    )
    await final_release(
        session,
        task_id=shot.id,
        quantity=Decimal("3"),
        actor_id=fx["user"].id,
    )

    # Отдельная позиция: этап без входа закрывается остатками ГХП при
    # выпуске партии — автозавершение пишет COMPLETE само.
    auto_fx = await build_operation_route(
        session,
        sku="NOINVREL",
        stages=[
            ("Подготовка", SECTION_TYPE_PRODUCTION, ["CUT_PREP"]),
            ("Пила", SECTION_TYPE_PRODUCTION, ["SAW"]),
        ],
        transform_at=2,
        with_plan_lines=False,
        position_input_quantity=Decimal("0"),
        position_outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}
        ],
    )
    batch = await create_release_batch(
        session,
        production_plan_id=auto_fx["plan"].id,
        positions=[
            {"plan_position_id": auto_fx["position"].id, "release_quantity": "100"}
        ],
    )
    await release_batch(session, batch["id"])
    await session.commit()
    await assert_no_invariants_violations(session, context="no-null-ops")

    plan_txs = await _txs(session)
    plan_txs = [tx for tx in plan_txs if tx.task_id is not None]
    reasons = {tx.reason for tx in plan_txs}
    assert {
        Reason.TRANSFER_SEND,
        Reason.TRANSFER_RECEIVE,
        Reason.COMPLETE,
        Reason.SCRAP,
        Reason.FINAL_RELEASE,
    } <= reasons, f"сквозной сценарий не накрыл пути записи: {reasons}"
    null_ops = [
        (tx.id, tx.reason.value) for tx in plan_txs if tx.completed_operations is None
    ]
    assert null_ops == [], f"плановые проводки без признака: {null_ops}"


# ─── источник признака: операции СЕКЦИИ, а не операции этапа ─────────────────


async def test_completed_operations_come_from_section_operations(
    session: AsyncSession,
) -> None:
    """Признак выводится из справочника операций секций (ADR-0021).

    У каждой секции маршрута в фикстуре есть операции уровня ЭТАПА с
    другими кодами (``<код>@STAGE``) — если бы резолвер читал ``route_operations``
    вместо ``section_operations``, проводка получила бы чужие коды.
    """
    fx = await build_operation_route(session, sku="REFSRC", stages=TASK_STAGES)
    shot = fx["tasks"][2]
    await _issue_to_task(session, fx, shot, qty=Decimal("100"))
    await complete_task(
        session,
        task_id=shot.id,
        good_quantity=Decimal("10"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()

    tx = await _only_tx(session, reason=Reason.COMPLETE, task_id=shot.id)
    assert tx.completed_operations == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW", "SHOT"]
    assert not any("@STAGE" in code for code in tx.completed_operations)



# ─── финальный выпуск и автозавершение при выпуске партии ───────────────────


async def test_final_release_carries_task_stage_operations(
    session: AsyncSession,
) -> None:
    """FINAL_RELEASE несёт операции финального этапа маршрута задания.

    Проводка плановaya (task_id задания), но вызывающий признак не передаёт —
    он выводится из маршрута так же, как на остальных путях.
    """
    fx = await build_operation_route(
        session,
        sku="FINREL",
        stages=[
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            ("Сборка", SECTION_TYPE_PRODUCTION, ["ASSEMBLY", "QC"]),
        ],
    )
    assembly = fx["tasks"][1]
    # Адресат финального выпуска: склад ГП, помеченный дефолтом (#137).
    output_stock = Section(
        code="FINREL-FG",
        name="Склад ГП",
        type=SECTION_TYPE_FINISHED_STOCK,
        is_active=True,
        sort_order=90,
        is_output_default=True,
    )
    session.add(output_stock)
    await session.commit()

    await _issue_to_task(session, fx, assembly, qty=Decimal("100"))
    await complete_task(
        session,
        task_id=assembly.id,
        good_quantity=Decimal("8"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    released = await final_release(
        session,
        task_id=assembly.id,
        quantity=Decimal("8"),
        actor_id=fx["user"].id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="final-release-ops")

    assert released["transaction_id"] is not None
    tx = await _only_tx(session, reason=Reason.FINAL_RELEASE, task_id=assembly.id)
    assert tx.completed_operations == ["ASSEMBLY", "ISSUE_RAW", "QC"]
    assert tx.completed_operations == ops_through(
        [
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            ("Сборка", SECTION_TYPE_PRODUCTION, ["ASSEMBLY", "QC"]),
        ],
        2,
    )


async def test_auto_release_remainder_completion_carries_operations(
    session: AsyncSession,
) -> None:
    """Автозавершение этапа при выпуске партии несёт признак маршрута.

    ``plan_generation.release_batch`` помечает этап как полностью покрытый
    и сам пишет COMPLETE с ``task_id``. Материал приходит из остатков ГХП,
    но этап маршрутный — признак выводится из его позиции, а не остаётся
    NULL. Покрыт только первый этап: у него нет входа (сырьё не требуется),
    поэтому плановое количество ноль и ветка автозавершения срабатывает.
    """
    fx = await build_operation_route(
        session,
        sku="AUTOREL",
        stages=[
            ("Подготовка", SECTION_TYPE_PRODUCTION, ["CUT_PREP"]),
            ("Пила", SECTION_TYPE_PRODUCTION, ["SAW"]),
        ],
        transform_at=2,
        with_plan_lines=False,
        position_input_quantity=Decimal("0"),
        position_outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}
        ],
    )

    batch = await create_release_batch(
        session,
        production_plan_id=fx["plan"].id,
        positions=[{"plan_position_id": fx["position"].id, "release_quantity": "100"}],
    )
    await release_batch(session, batch["id"])
    await session.commit()
    await assert_no_invariants_violations(session, context="auto-release-ops")

    auto = await _only_tx(session, reason=Reason.COMPLETE)
    assert auto.source_ref == "auto_release_remainder"
    assert auto.task_id is not None
    # Признак ограничен первым этапом: операции «Пилы» материал ещё не проходил.
    assert auto.completed_operations == ["CUT_PREP"]
