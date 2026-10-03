"""Выбор источника при взятии задания в работу (#314).

Диалог взятия в работу показывает остатки и предлагает выбрать источник
выдачи; выбор едет в ``take-to-work`` и обязан физически менять, откуда
взялся материал. Ключ выбора — строка ``stock_balances`` (ADR-0055: пять
осей ключа), а адресат выдачи — этап, вход которого совпадает с
признаком операций остатка: сырьё со склада уходит на первый
производственный этап, материал после пресса — на следующий.
"""
from decimal import Decimal

from app.models.user import User
from app.models.work_task import WorkTask
from app.stock.models import StockBalance, StockTransaction
from sqlalchemy import select

from tests.helpers.transfers import _make_dim_route_fixture, _seed_balance
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)

# Маршрут фикстуры: raw(seq1, ISSUE_RAW) → p1(seq2, P1_OP) → p2(seq3, P2_OP).
# Вход p1 — материал, прошедший ISSUE_RAW; вход p2 — ISSUE_RAW + P1_OP.
RAW_OPS = ["ISSUE_RAW"]
PREP_OPS = ["ISSUE_RAW", "P1_OP"]


async def _seed_user(session) -> User:
    """Один сид-оператор на модуль: тесты делят схему, а email уникален."""
    user = await session.scalar(select(User).where(User.email == "src@local"))
    if user is None:
        user = await _make_user(session, "src@local")
    return user


async def _latest_balance(session, *, product_id, location_id) -> StockBalance:
    return (
        await session.execute(
            select(StockBalance)
            .where(
                StockBalance.product_id == product_id,
                StockBalance.location_id == location_id,
            )
            .order_by(StockBalance.id.desc())
            .limit(1)
        )
    ).scalar_one()


async def _balance(session, *, product_id, location_id, qty, ops) -> StockBalance:
    user = await _seed_user(session)
    await _seed_balance(
        session,
        user_id=user.id,
        location_id=location_id,
        product_id=product_id,
        qty=qty,
        ops=ops,
    )
    return await _latest_balance(
        session, product_id=product_id, location_id=location_id
    )


async def _take(client, position_id, user, allocation=None) -> dict:
    payload = {"position_ids": [position_id]}
    if allocation is not None:
        payload["remainder_allocation"] = allocation
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json=payload,
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    return body["results"][0]


async def _sends(session) -> list[StockTransaction]:
    return list(
        (
            await session.execute(
                select(StockTransaction)
                .where(StockTransaction.reason == "transfer_send")
                .order_by(StockTransaction.id)
            )
        ).scalars().all()
    )


async def test_source_issues_to_stage_whose_input_matches_operations(client, session) -> None:
    """Выбранный остаток списывается и приходит на свой этап, а не «куда-нибудь»."""
    fx = await _make_dim_route_fixture(session, sku="SRC1", qty=Decimal(100))
    raw, p1, _p2 = fx["sections"]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(100),
        ops=RAW_OPS,
    )

    user = await _make_user(session, "op1@local")
    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "40"}],
    )

    assert result["status"] == "success", result
    sends = await _sends(session)
    assert len(sends) == 1, "выбор источника обязан дать ровно одну проводку выдачи"
    send = sends[0]
    assert send.from_location_id == raw.id
    assert send.to_location_id == p1.id, "сырьё со склада уходит на первый production-этап"
    assert send.quantity == Decimal(40)
    assert send.source_ref == "take_to_work_source"

    task = (
        await session.execute(select(WorkTask).where(WorkTask.section_id == p1.id))
    ).scalar_one()
    assert send.task_id is None, (
        "остаток снят со склада до появления задания: приписывать проводку "
        "заданию значит вырастить «передано» в бюджете участка"
    )
    assert task.section_plan_line_id is not None

    left = (
        await session.execute(
            select(StockBalance).where(StockBalance.id == balance.id)
        )
    ).scalar_one()
    assert left.balance_qty == Decimal(60)
    await assert_no_invariants_violations(session)
    await assert_no_stock_ledger_invariants_violations(session)


async def test_prep_stock_source_skips_stage_its_operations_cleared(client, session) -> None:
    """Материал после пресса идёт на следующий этап, а не на первый.

    Предвыбор по убыванию операций (#314) выбирает подготовительный склад
    именно затем, что он ближе к концу маршрута: его вход — уже закрытый
    этап, и выдавать его на первый этап нельзя (ADR-0055 п.7).
    """
    fx = await _make_dim_route_fixture(session, sku="SRC2", qty=Decimal(100))
    raw, _p1, p2 = fx["sections"]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(60),
        ops=PREP_OPS,
    )

    user = await _make_user(session, "op2@local")
    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "60"}],
    )

    assert result["status"] == "success", result
    sends = await _sends(session)
    assert len(sends) == 1
    assert sends[0].to_location_id == p2.id


async def test_take_to_work_without_source_moves_no_stock(client, session) -> None:
    """Контроль: без выбора источника запуск не двигает материал."""
    fx = await _make_dim_route_fixture(session, sku="SRC3", qty=Decimal(100))
    raw = fx["sections"][0]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(100),
        ops=RAW_OPS,
    )

    user = await _make_user(session, "op3@local")
    result = await _take(client, fx["position"].id, user)

    assert result["status"] == "success", result
    assert await _sends(session) == []
    left = (
        await session.execute(
            select(StockBalance).where(StockBalance.id == balance.id)
        )
    ).scalar_one()
    assert left.balance_qty == Decimal(100)


async def test_source_caps_at_available_balance(client, session) -> None:
    """Запрошено больше, чем лежит, — выдаётся остаток, склад не уходит в минус."""

    fx = await _make_dim_route_fixture(session, sku="SRC4", qty=Decimal(100))
    raw = fx["sections"][0]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(30),
        ops=RAW_OPS,
    )

    user = await _make_user(session, "op4@local")
    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "100"}],
    )

    assert result["status"] == "success", result
    sends = await _sends(session)
    assert len(sends) == 1
    assert sends[0].quantity == Decimal(30)
    # Списанная в ноль строка остатка материализации не держит: её отсутствие
    # и есть «склад не ушёл в минус».
    left = await session.scalar(
        select(StockBalance).where(StockBalance.id == balance.id)
    )
    assert left is None


async def test_source_of_another_product_is_rejected(client, session) -> None:
    """Остаток чужого товара — отказ с причиной, а не тихая выдача."""
    fx = await _make_dim_route_fixture(session, sku="SRC5", qty=Decimal(100))
    other = await _make_dim_route_fixture(session, sku="SRC5X", qty=Decimal(50))
    balance = await _balance(
        session,
        product_id=other["product"].id,
        location_id=other["sections"][0].id,
        qty=Decimal(50),
        ops=RAW_OPS,
    )

    user = await _make_user(session, "op5@local")
    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "10"}],
    )

    assert result["status"] == "failed", result
    assert "другого товара" in (result["reason"] or "")
    assert await _sends(session) == []


async def test_source_operations_outside_route_is_rejected(client, session) -> None:
    """Материал, чей признак операций не встречается на маршруте, не выдаётся."""
    fx = await _make_dim_route_fixture(session, sku="SRC6", qty=Decimal(100))
    raw = fx["sections"][0]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(50),
        ops=["P2_OP"],
    )

    user = await _make_user(session, "op6@local")
    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "10"}],
    )

    assert result["status"] == "failed", result
    assert "не подходит маршруту" in (result["reason"] or "")
    assert await _sends(session) == []


async def test_source_with_unrecorded_operations_is_rejected(client, session) -> None:
    """``NULL``-группа (состояние не зафиксировано) выдачей быть не может.

    Списание точное (ADR-0055 п.3): такую строку нельзя списать на маршрут,
    и «выдать куда-нибудь» значило бы продать несуществующий остаток.
    """
    from app.stock.services import Reason, StockCommand, StockCommandService

    fx = await _make_dim_route_fixture(session, sku="SRC7", qty=Decimal(100))
    raw = fx["sections"][0]
    user = await _make_user(session, "op7@local")
    # Ручной приход без признака кладёт остаток в NULL-группу.
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=raw.id,
            quantity=Decimal(50),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    await session.commit()
    balance = await _latest_balance(
        session, product_id=fx["product"].id, location_id=raw.id
    )
    assert balance.completed_operations is None

    result = await _take(
        client,
        fx["position"].id,
        user,
        [{"balance_id": balance.id, "quantity": "10"}],
    )

    assert result["status"] == "failed", result
    assert "не зафиксировано" in (result["reason"] or "")
    assert await _sends(session) == []


async def test_source_rejected_for_bulk_take_to_work(client, session) -> None:
    """Выбор источника — решение для одной позиции; молчаливый дроп хуже отказа."""
    fx = await _make_dim_route_fixture(session, sku="SRC8", qty=Decimal(100))
    raw = fx["sections"][0]
    balance = await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(100),
        ops=RAW_OPS,
    )
    user = await _make_user(session, "op8@local")

    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={
            "position_ids": [fx["position"].id, fx["position"].id],
            "remainder_allocation": [{"balance_id": balance.id, "quantity": "10"}],
        },
        headers=_auth_headers(user),
    )
    assert resp.status_code == 422, resp.text
    assert "только для одной позиции" in resp.json()["detail"]


async def test_by_product_order_operations_ranks_prep_above_raw(client, session) -> None:
    """``order=operations`` — порядок кандидатов выдачи: больше операций выше."""
    fx = await _make_dim_route_fixture(session, sku="SRC9", qty=Decimal(100))
    raw = fx["sections"][0]
    prep_sec = fx["sections"][2]
    await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(100),
        ops=[],
    )
    await _balance(
        session,
        product_id=fx["product"].id,
        location_id=prep_sec.id,
        qty=Decimal(40),
        ops=PREP_OPS,
    )
    user = await _make_user(session, "op9@local")

    resp = await client.get(
        f"/api/stock/balance/by-product/{fx['product'].id}?order=operations",
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["location_id"] for r in rows] == [prep_sec.id, raw.id], (
        "подготовительный склад (2 операции) должен идти выше сырья (0)"
    )

    key_resp = await client.get(
        f"/api/stock/balance/by-product/{fx['product'].id}",
        headers=_auth_headers(user),
    )
    assert [r["location_id"] for r in key_resp.json()] == [raw.id, prep_sec.id], (
        "порядок полного ключа (ADR-0055 п.11) не меняется"
    )


async def test_by_product_order_operations_puts_unrecorded_last(client, session) -> None:
    """Незафиксированное состояние операций — кандидат хуже любого учтённого."""
    from app.stock.services import Reason, StockCommand, StockCommandService
    fx = await _make_dim_route_fixture(session, sku="SRC10", qty=Decimal(100))

    raw, p1, p2 = fx["sections"]
    user = await _make_user(session, "op10@local")
    await _balance(
        session,
        product_id=fx["product"].id,
        location_id=raw.id,
        qty=Decimal(100),
        ops=[],
    )
    await _balance(
        session,
        product_id=fx["product"].id,
        location_id=p1.id,
        qty=Decimal(20),
        ops=RAW_OPS,
    )
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=p2.id,
            quantity=Decimal(10),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    await session.commit()
    assert (
        await _latest_balance(session, product_id=fx["product"].id, location_id=p2.id)
    ).completed_operations is None

    resp = await client.get(
        f"/api/stock/balance/by-product/{fx['product'].id}?order=operations",
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert [r["location_id"] for r in resp.json()] == [p1.id, raw.id, p2.id], (
        "в DESC без coalesce строки с NULL ушли бы в начало и стали "
        "предвыбранным источником; ничью по числу операций решает location_id"
    )
