"""Тесты габаритов (dimensions) в Stock Ledger — issue #4, ADR-0001.

Покрывают:
- Каноническая форма при записи: {"length_mm": 2700.0} → {"length_mm": 2700}.
- Невалидный габарит → StockValidationError (API → 422).
- Баланс группируется по product + location + quality + dimensions;
  разные длины одного SKU — разные строки, NULL — отдельная legacy-группа.
- Отрицательный баланс проверяется в разрезе габаритной группы:
  списание сверх остатка конкретной длины отклоняется.
- rebuild_all_balances воспроизводит габаритные группы.
- transfer_send переносит габарит на обе проводки (SEND + RECEIVE),
  cancel-компенсация гасит ту же группу; инварианты S1-S6 проходят.
- POST /api/stock/adjustment принимает dimensions; GET /balance отдаёт
  dimensions + dimensions_label («2,7 м»).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.work_task import WorkTask
from app.stock import (
    QualityState,
    Reason,
    StockBalance,
    StockCommand,
    StockCommandService,
    StockProjectionManager,
    StockTransaction,
    StockValidationError,
)
from app.stock.services import dimensions_match_clause
from app.transfers.services import cancel_transfer, transfer_send
from tests.test_integrity_invariants import (
    assert_no_stock_ledger_invariants_violations,
)
from tests.stock.test_transfer_stage2 import (
    _make_two_ghp_setup,
    _release_via_take_to_work,
)

pytestmark = pytest.mark.asyncio

DIMS_27 = {"length_mm": 2700}
DIMS_30 = {"length_mm": 3000}


# ─── helpers ────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str = "dims-tester") -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        full_name="Dims Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session: AsyncSession, sku: str = "PROFILE") -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    loc_type: str = "raw_stock",
) -> Section:
    section = Section(
        code=code,
        name=name,
        type=loc_type,
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _balance(
    session: AsyncSession,
    product_id: int,
    location_id: int,
    dims: dict | None,
    quality_state: QualityState = QualityState.GOOD,
) -> Decimal:
    """Остаток конкретной габаритной группы (NULL — legacy-группа)."""
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == quality_state,
            dimensions_match_clause(StockBalance.dimensions, dims),
        )
    )
    bal = row.scalar_one_or_none()
    return bal.balance_qty if bal else Decimal("0")


async def _manual_in(
    session: AsyncSession,
    svc: StockCommandService,
    *,
    product_id: int,
    location_id: int,
    qty: str,
    dims: dict | None,
    user_id: int,
) -> StockTransaction:
    return await svc.record(session, StockCommand(
        product_id=product_id,
        to_location_id=location_id,
        quantity=Decimal(qty),
        reason=Reason.MANUAL_IN,
        dimensions=dims,
        created_by=user_id,
    ))


# ─── canonical form ──────────────────────────────────────────────────────────


async def test_record_stores_canonical_dimensions(session: AsyncSession) -> None:
    """{"length_mm": 2700.0} сохраняется как {"length_mm": 2700} (int)."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-C1", name="Stock C1")

    svc = StockCommandService()
    tx = await _manual_in(
        session, svc,
        product_id=product.id, location_id=stock.id,
        qty="10", dims={"length_mm": 2700.0}, user_id=user.id,
    )
    await session.flush()

    # Перечитываем из БД — канон в ledger и в балансе.
    stored = await session.get(StockTransaction, tx.id)
    assert stored is not None
    assert stored.dimensions == DIMS_27
    assert isinstance(stored.dimensions["length_mm"], int)
    assert await _balance(session, product.id, stock.id, DIMS_27) == Decimal("10")


async def test_record_empty_dict_dimensions_becomes_null(session: AsyncSession) -> None:
    """{} эквивалентен None — попадает в legacy-группу."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-C2", name="Stock C2")

    svc = StockCommandService()
    tx = await _manual_in(
        session, svc,
        product_id=product.id, location_id=stock.id,
        qty="5", dims={}, user_id=user.id,
    )
    assert tx.dimensions is None
    assert await _balance(session, product.id, stock.id, None) == Decimal("5")


async def test_record_rejects_invalid_dimensions(session: AsyncSession) -> None:
    """Отрицательная длина → StockValidationError, ledger чист."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-C3", name="Stock C3")

    svc = StockCommandService()
    with pytest.raises(StockValidationError):
        await _manual_in(
            session, svc,
            product_id=product.id, location_id=stock.id,
            qty="5", dims={"length_mm": -5}, user_id=user.id,
        )
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert txs == []


# ─── balance grouping ────────────────────────────────────────────────────────


async def test_balance_separates_lengths_and_legacy(session: AsyncSession) -> None:
    """200×2,7 м + 50×3,0 м + 30×NULL — три независимых остатка одного SKU."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-G1", name="Stock G1")

    svc = StockCommandService()
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="200", dims=DIMS_27, user_id=user.id)
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="50", dims=DIMS_30, user_id=user.id)
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="30", dims=None, user_id=user.id)

    assert await _balance(session, product.id, stock.id, DIMS_27) == Decimal("200")
    assert await _balance(session, product.id, stock.id, DIMS_30) == Decimal("50")
    assert await _balance(session, product.id, stock.id, None) == Decimal("30")

    rows = (await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == stock.id,
        )
    )).scalars().all()
    assert len(rows) == 3
    await assert_no_stock_ledger_invariants_violations(session, context="dims-groups")


async def test_writeoff_over_specific_length_rejected(session: AsyncSession) -> None:
    """Списание 150×2,7 м при остатке 100×2,7 м отклоняется,
    даже если по 3,0 м остаток есть."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-N1", name="Stock N1")

    svc = StockCommandService()
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="100", dims=DIMS_27, user_id=user.id)
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="100", dims=DIMS_30, user_id=user.id)

    with pytest.raises(StockValidationError, match="Insufficient stock"):
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=stock.id,
            quantity=Decimal("150"),
            reason=Reason.MANUAL_OUT,
            dimensions=DIMS_27,
            created_by=user.id,
        ))

    # В пределах остатка группы — проходит.
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=stock.id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_OUT,
        dimensions=DIMS_27,
        created_by=user.id,
    ))
    assert await _balance(session, product.id, stock.id, DIMS_27) == Decimal("0")
    assert await _balance(session, product.id, stock.id, DIMS_30) == Decimal("100")


async def test_writeoff_with_dims_from_legacy_only_stock_rejected(session: AsyncSession) -> None:
    """NULL-остаток не покрывает списание с габаритом, и наоборот."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-N2", name="Stock N2")

    svc = StockCommandService()
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="40", dims=None, user_id=user.id)

    with pytest.raises(StockValidationError, match="Insufficient stock"):
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=stock.id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_OUT,
            dimensions=DIMS_27,
            created_by=user.id,
        ))

    # Из legacy-группы списание проходит.
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=stock.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_OUT,
        dimensions=None,
        created_by=user.id,
    ))
    assert await _balance(session, product.id, stock.id, None) == Decimal("30")


async def test_rebuild_all_balances_preserves_dimension_groups(session: AsyncSession) -> None:
    """Полный пересчёт из ledger восстанавливает габаритные группы."""
    user = await _make_user(session)
    product = await _make_product(session)
    stock = await _make_location(session, code="DIM-R1", name="Stock R1")

    svc = StockCommandService()
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="200", dims=DIMS_27, user_id=user.id)
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="50", dims=DIMS_30, user_id=user.id)
    await _manual_in(session, svc, product_id=product.id, location_id=stock.id,
                     qty="30", dims=None, user_id=user.id)
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=stock.id,
        quantity=Decimal("50"),
        reason=Reason.MANUAL_OUT,
        dimensions=DIMS_27,
        created_by=user.id,
    ))

    pm = StockProjectionManager()
    await pm.rebuild_all_balances(session)
    await session.flush()

    assert await _balance(session, product.id, stock.id, DIMS_27) == Decimal("150")
    assert await _balance(session, product.id, stock.id, DIMS_30) == Decimal("50")
    assert await _balance(session, product.id, stock.id, None) == Decimal("30")
    await assert_no_stock_ledger_invariants_violations(session, context="dims-rebuild")


# ─── transfer preserves dimensions ───────────────────────────────────────────


async def _make_tasks_transferable_with_dims(
    session: AsyncSession,
    client,
    setup: dict,
    *,
    dims: dict | None,
) -> dict:
    """Take-to-work + seed остатка с габаритом на исходной секции.

    Аналог ``_make_tasks_transferable`` из test_transfer_stage2, но весь
    материал заводится в габаритной группе ``dims``, чтобы transfer_send
    с тем же габаритом проходил проверку остатка группы.
    """
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(
        select(WorkTask)
        .where(WorkTask.product_id == setup["product"].id)
        .order_by(WorkTask.id)
    )).scalars().all()
    assert len(tasks) >= 2
    src, dst = tasks[0], tasks[1]

    stock = await _make_location(
        session, code=f"{setup['product'].sku}-STK", name="Stock", loc_type="raw_stock",
    )
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        to_location_id=stock.id,
        quantity=src.planned_quantity,
        reason=Reason.MANUAL_IN,
        dimensions=dims,
        created_by=setup["user"].id,
    ))
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=stock.id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.TRANSFER_RECEIVE,
        dimensions=dims,
        task_id=src.id,
        created_by=setup["user"].id,
    ))
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=src.section_id,
        to_location_id=src.section_id,
        quantity=src.planned_quantity,
        reason=Reason.COMPLETE,
        dimensions=dims,
        task_id=src.id,
        source_ref="test_seed_dims",
        created_by=setup["user"].id,
    ))
    await session.flush()
    return {"from_task_id": src.id, "to_task_id": dst.id, "user": setup["user"]}


async def test_transfer_send_preserves_dimensions(session: AsyncSession, client) -> None:
    """SEND и RECEIVE несут один габарит; баланс двигается в группе габарита;
    cancel-компенсация возвращает ту же группу; инварианты проходят."""
    setup = await _make_two_ghp_setup(session, sku="DIMTR", qty=Decimal("10"))
    ctx = await _make_tasks_transferable_with_dims(session, client, setup, dims=DIMS_27)

    from_task = await session.get(WorkTask, ctx["from_task_id"])
    to_task = await session.get(WorkTask, ctx["to_task_id"])

    result = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("4"),
        actor_id=ctx["user"].id,
        idempotency_key="dimtr:send",
        dimensions={"length_mm": 2700.0},  # неканоническая форма на входе
    )
    assert result["status"] == "accepted"
    await session.flush()

    txs = (await session.execute(
        select(StockTransaction)
        .where(StockTransaction.transfer_id == result["transfer_id"])
        .order_by(StockTransaction.id)
    )).scalars().all()
    assert len(txs) == 2
    assert txs[0].reason == Reason.TRANSFER_SEND
    assert txs[1].reason == Reason.TRANSFER_RECEIVE
    assert txs[0].dimensions == DIMS_27
    assert txs[1].dimensions == DIMS_27

    # Баланс двигается внутри группы 2,7 м.
    assert await _balance(
        session, from_task.product_id, from_task.section_id, DIMS_27,
    ) == Decimal("6")
    assert await _balance(
        session, to_task.product_id, to_task.section_id, DIMS_27,
    ) == Decimal("4")
    await assert_no_stock_ledger_invariants_violations(session, context="dims-transfer")

    # Cancel: компенсации гасят ту же габаритную группу.
    await cancel_transfer(
        session,
        transfer_id=result["transfer_id"],
        actor_id=ctx["user"].id,
        comment="dims cancel",
    )
    await session.flush()
    comp_txs = (await session.execute(
        select(StockTransaction).where(
            StockTransaction.transfer_id == result["transfer_id"],
            StockTransaction.compensates_tx_id.is_not(None),
        )
    )).scalars().all()
    assert len(comp_txs) == 2
    assert all(tx.dimensions == DIMS_27 for tx in comp_txs)
    assert await _balance(
        session, from_task.product_id, from_task.section_id, DIMS_27,
    ) == Decimal("10")
    assert await _balance(
        session, to_task.product_id, to_task.section_id, DIMS_27,
    ) == Decimal("0")
    await assert_no_stock_ledger_invariants_violations(session, context="dims-cancel")


async def test_transfer_send_over_dims_group_balance_rejected(
    session: AsyncSession, client,
) -> None:
    """Материал на секции лежит без габарита — отправка с габаритом
    отклоняется проверкой остатка группы."""
    setup = await _make_two_ghp_setup(session, sku="DIMTX", qty=Decimal("10"))
    ctx = await _make_tasks_transferable_with_dims(session, client, setup, dims=None)

    with pytest.raises(StockValidationError, match="Insufficient stock"):
        await transfer_send(
            session,
            from_task_id=ctx["from_task_id"],
            to_task_id=ctx["to_task_id"],
            quantity=Decimal("4"),
            actor_id=ctx["user"].id,
            dimensions=DIMS_30,
        )


# ─── API: adjustment + balance ───────────────────────────────────────────────


async def test_adjustment_api_roundtrip_with_dimensions(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """POST /adjustment с dimensions → 201; GET /balance отдаёт
    dimensions и dimensions_label по группам."""
    product = await _make_product(session, sku="DIM-API")
    location = await _make_location(session, code="DIM-API-L", name="Dim Api Loc")
    await session.commit()

    for qty, dims in ((200.0, {"length_mm": 2700.0}), (50.0, {"length_mm": 3000}), (30.0, None)):
        resp = await client.post("/api/stock/adjustment", json={
            "product_id": product.id,
            "location_id": location.id,
            "quantity": qty,
            "reason": "manual_in",
            "quality_state": "good",
            "dimensions": dims,
        })
        assert resp.status_code == 201, resp.text

    resp = await client.get(f"/api/stock/balance?product_id={product.id}")
    assert resp.status_code == 200, resp.text
    balances = resp.json()["balances"]
    assert len(balances) == 3
    by_label = {b["dimensions_label"]: b for b in balances}
    assert set(by_label) == {"2,7 м", "3 м", "—"}
    assert by_label["2,7 м"]["dimensions"] == DIMS_27
    assert float(by_label["2,7 м"]["balance_qty"]) == 200.0
    assert by_label["3 м"]["dimensions"] == DIMS_30
    assert by_label["—"]["dimensions"] is None
    assert float(by_label["—"]["balance_qty"]) == 30.0

    # Транзакции тоже несут габарит.
    resp = await client.get(f"/api/stock/transactions?product_id={product.id}")
    assert resp.status_code == 200
    tx_dims = {tx["dimensions_label"] for tx in resp.json()["transactions"]}
    assert tx_dims == {"2,7 м", "3 м", "—"}


async def test_adjustment_api_invalid_dimensions_422(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Некорректный габарит → 422, списание сверх группы → 422."""
    product = await _make_product(session, sku="DIM-API2")
    location = await _make_location(session, code="DIM-API2-L", name="Dim Api Loc 2")
    await session.commit()

    resp = await client.post("/api/stock/adjustment", json={
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 5.0,
        "reason": "manual_in",
        "dimensions": {"length_mm": 0},
    })
    assert resp.status_code == 422, resp.text
    assert "dimensions" in resp.json()["detail"]

    # Приход 10×2,7 м, попытка списать 20×2,7 м → 422 (остаток группы).
    resp = await client.post("/api/stock/adjustment", json={
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 10.0,
        "reason": "manual_in",
        "dimensions": {"length_mm": 2700},
    })
    assert resp.status_code == 201, resp.text
    resp = await client.post("/api/stock/adjustment", json={
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 20.0,
        "reason": "manual_out",
        "dimensions": {"length_mm": 2700},
    })
    assert resp.status_code == 422, resp.text
    assert "Insufficient stock" in resp.json()["detail"]
