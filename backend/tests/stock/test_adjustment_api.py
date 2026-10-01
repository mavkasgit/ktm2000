"""Тесты POST /api/stock/adjustment.

Проверяют:
- Создание StockTransaction при manual_in / manual_out
- Обновление баланса (приход / расход)
- Валидацию reason (неверный → 422)
- Признак «пройденные операции» (ADR-0055 п.3, п.12): payload принимает
  ``completed_operations``, списание ищет выбранную группу, приход без
  выбора ложится в NULL-группу, неизвестный код отклоняется тем же
  путём, что и у плановых проводок
"""
from __future__ import annotations

import json

import pytest
from app.models import Product, ProductType, Section
from app.models.route import SectionOperation
from app.stock.models import Reason, StockBalance, StockTransaction
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _make_product(session: AsyncSession, sku: str = "ADJ-PROD") -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, code: str = "STOCK-1") -> Section:
    section = Section(
        code=code, name=code, type="raw_stock", is_active=True, sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _register_operations(
    session: AsyncSession, location: Section, codes: list[str]
) -> None:
    """Коды операций в справочнике ``section_operations`` — иначе
    ``record()`` отклонит признак как неизвестный (ADR-0043)."""
    for order, code in enumerate(codes, start=1):
        session.add(
            SectionOperation(
                section_id=location.id,
                operation_code=code,
                operation_name=code,
                is_significant=True,
                sort_order=order,
            )
        )
    await session.flush()


async def _balance_rows(session: AsyncSession, product: Product) -> list[StockBalance]:
    """Строки баланса артикула.

    ``populate_existing`` — API уже мог закоммитить обновлённый баланс, а
    ``expire_all`` здесь небезопасен: следующее обращение к атрибуту
    протухшего ``product`` сделало бы ленивую загрузку вне greenlet'а.
    """
    rows = await session.execute(
        select(StockBalance)
        .where(StockBalance.product_id == product.id)
        .order_by(StockBalance.id.asc())
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


def _row_by_ops(rows: list[StockBalance], ops: list[str] | None) -> StockBalance | None:
    """Строка баланса с данным признаком: ``None`` и ``[]`` — разные группы."""
    for row in rows:
        if json.dumps(row.completed_operations, ensure_ascii=False) == json.dumps(
            ops, ensure_ascii=False
        ):
            return row
    return None


def _payload(product: Product, location: Section, **overrides) -> dict:
    payload: dict = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 10.0,
        "reason": "manual_in",
        "quality_state": "good",
    }
    payload.update(overrides)
    return payload


async def test_adjustment_in_creates_stock_tx(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с reason=manual_in → 201, StockTransaction создан, баланс вырос."""
    product = await _make_product(session)
    location = await _make_location(session)
    await session.commit()

    payload = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 10.0,
        "reason": "manual_in",
        "quality_state": "good",
        "comment": "тестовый приход",
    }
    resp = await client.post("/api/stock/adjustment", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reason"] == "manual_in"
    assert float(body["quantity"]) == 10.0

    # Проверяем что транзакция создана
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 1
    tx = txs[0]
    assert tx.product_id == product.id
    assert tx.to_location_id == location.id
    assert tx.from_location_id is None
    assert tx.reason == Reason.MANUAL_IN
    assert float(tx.quantity) == 10.0

    # Баланс должен быть 10
    balance = (await session.execute(select(StockBalance))).scalar_one_or_none()
    assert balance is not None
    assert float(balance.balance_qty) == 10.0
    assert balance.location_id == location.id


async def test_adjustment_out_creates_stock_tx(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с reason=manual_out → 201, StockTransaction создан, баланс уменьшен."""
    product = await _make_product(session)
    location = await _make_location(session)

    # Сначала создаём приход, чтобы был баланс
    await _make_product(session, "ADJ-PROD2")

    payload_in = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 100.0,
        "reason": "manual_in",
        "quality_state": "good",
    }
    resp_in = await client.post("/api/stock/adjustment", json=payload_in)
    assert resp_in.status_code == 201

    # Расход
    payload_out = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 30.0,
        "reason": "manual_out",
        "quality_state": "good",
    }
    resp_out = await client.post("/api/stock/adjustment", json=payload_out)
    assert resp_out.status_code == 201, resp_out.text
    body = resp_out.json()
    assert body["reason"] == "manual_out"
    assert float(body["quantity"]) == 30.0

    # Транзакций должно быть 2 (приход + расход)
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 2

    # Баланс = 100 - 30 = 70
    balance = (await session.execute(
        select(StockBalance).where(StockBalance.product_id == product.id)
    )).scalar_one_or_none()
    assert balance is not None
    assert float(balance.balance_qty) == 70.0


async def test_adjustment_validates_reason(client: AsyncClient, session: AsyncSession) -> None:
    """POST /adjustment с невалидным reason → 422."""
    product = await _make_product(session)
    location = await _make_location(session)
    await session.commit()

    payload = {
        "product_id": product.id,
        "location_id": location.id,
        "quantity": 5.0,
        "reason": "complete",  # недопустимый reason для adjustment
    }
    resp = await client.post("/api/stock/adjustment", json=payload)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "reason" in detail.lower() or "complete" in detail


# ─── Признак операций в payload (ADR-0055 п.3, п.12) ────────────────────────


async def test_adjustment_in_to_named_group(client: AsyncClient, session: AsyncSession) -> None:
    """Приход с completed_operations кладётся в именованную группу.

    Канонизация та же, что у плановых проводок: дубли снимаются, порядок —
    по возрастанию кода, в ledger и в балансе лежит канонический список.
    """
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW", "PACK"])
    await session.commit()

    resp = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, completed_operations=["PACK", "SAW", "SAW"]),
    )
    assert resp.status_code == 201, resp.text

    tx = (await session.execute(select(StockTransaction))).scalars().one()
    assert tx.completed_operations == ["PACK", "SAW"]

    rows = await _balance_rows(session, product)
    assert len(rows) == 1
    assert rows[0].completed_operations == ["PACK", "SAW"]
    assert float(rows[0].balance_qty) == 10.0


async def test_adjustment_in_without_operations_goes_to_null_group(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Приход без выбора → NULL-группа, и она НЕ смешивается с именованной."""
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    named = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, quantity=100.0, completed_operations=["SAW"]),
    )
    assert named.status_code == 201, named.text
    null_in = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, quantity=50.0),
    )
    assert null_in.status_code == 201, null_in.text

    rows = await _balance_rows(session, product)
    assert len(rows) == 2
    named_row = _row_by_ops(rows, ["SAW"])
    null_row = _row_by_ops(rows, None)
    assert named_row is not None and float(named_row.balance_qty) == 100.0
    assert null_row is not None and float(null_row.balance_qty) == 50.0

    # NULL-группа списывается целиком — именованная не затрагивается.
    out_null = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, quantity=50.0, reason="manual_out"),
    )
    assert out_null.status_code == 201, out_null.text

    rows = await _balance_rows(session, product)
    named_row = _row_by_ops(rows, ["SAW"])
    assert named_row is not None and float(named_row.balance_qty) == 100.0


async def test_adjustment_out_spends_selected_group(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Списание с указанным признаком уменьшает ТОЛЬКО выбранную группу."""
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    assert (
        await client.post(
            "/api/stock/adjustment",
            json=_payload(product, location, quantity=100.0, completed_operations=["SAW"]),
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/stock/adjustment",
            json=_payload(product, location, quantity=40.0),
        )
    ).status_code == 201

    out = await client.post(
        "/api/stock/adjustment",
        json=_payload(
            product, location, quantity=30.0, reason="manual_out",
            completed_operations=["SAW"],
        ),
    )
    assert out.status_code == 201, out.text

    rows = await _balance_rows(session, product)
    assert len(rows) == 2
    named_row = _row_by_ops(rows, ["SAW"])
    null_row = _row_by_ops(rows, None)
    assert named_row is not None and float(named_row.balance_qty) == 70.0
    assert null_row is not None and float(null_row.balance_qty) == 40.0

    # Признак расхода запоминается в самой проводке.
    txs = list(
        (
            await session.execute(
                select(StockTransaction).order_by(StockTransaction.id.asc())
            )
        ).scalars().all()
    )
    assert txs[-1].reason == Reason.MANUAL_OUT
    assert txs[-1].completed_operations == ["SAW"]


async def test_adjustment_out_from_other_group_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Списание «не той» группы → отказ с печатью признака в тексте ошибки.

    Участок при этом полон: материал лежит в именованной группе, а расход
    ищет NULL (или «без операций») — отката на соседнюю группу нет.
    """
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    assert (
        await client.post(
            "/api/stock/adjustment",
            json=_payload(product, location, quantity=100.0, completed_operations=["SAW"]),
        )
    ).status_code == 201

    # Без признака ищется NULL-группа — её нет.
    out_null = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, quantity=10.0, reason="manual_out"),
    )
    assert out_null.status_code == 422, out_null.text
    detail = out_null.json()["detail"]
    assert "completed_operations" in detail
    assert "не зафиксирован" in detail

    # Признак «маршрут пройден, операций не было» — тоже своя группа.
    out_empty = await client.post(
        "/api/stock/adjustment",
        json=_payload(
            product, location, quantity=10.0, reason="manual_out",
            completed_operations=[],
        ),
    )
    assert out_empty.status_code == 422, out_empty.text
    detail = out_empty.json()["detail"]
    assert "completed_operations" in detail
    assert "операций не было" in detail

    # Остаток именованной группы не тронут.
    rows = await _balance_rows(session, product)
    named_row = _row_by_ops(rows, ["SAW"])
    assert named_row is not None and float(named_row.balance_qty) == 100.0


async def test_adjustment_out_insufficient_in_selected_group(
    client: AsyncClient, session: AsyncSession
) -> None:
    """quantity > баланса выбранной группы → отказ с признаком и остатком."""
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    # Соседняя NULL-группа намеренно больше — она не должна спасти расход.
    assert (
        await client.post(
            "/api/stock/adjustment",
            json=_payload(product, location, quantity=100.0),
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/stock/adjustment",
            json=_payload(product, location, quantity=10.0, completed_operations=["SAW"]),
        )
    ).status_code == 201

    out = await client.post(
        "/api/stock/adjustment",
        json=_payload(
            product, location, quantity=30.0, reason="manual_out",
            completed_operations=["SAW"],
        ),
    )
    assert out.status_code == 422, out.text
    detail = out.json()["detail"]
    assert "SAW" in detail
    assert "required 30" in detail
    assert "available 10" in detail

    rows = await _balance_rows(session, product)
    named_row = _row_by_ops(rows, ["SAW"])
    null_row = _row_by_ops(rows, None)
    assert named_row is not None and float(named_row.balance_qty) == 10.0
    assert null_row is not None and float(null_row.balance_qty) == 100.0


async def test_adjustment_rejects_unknown_operation_code(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Неизвестный код → 422 тем же путём валидации, что и у плановых проводок."""
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    for reason in ("manual_in", "manual_out"):
        resp = await client.post(
            "/api/stock/adjustment",
            json=_payload(
                product, location, reason=reason,
                completed_operations=["SAW", "NOT_A_REAL_OP"],
            ),
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "unknown operation_code" in detail
        assert "NOT_A_REAL_OP" in detail

    # Ничего не записано: ни проводок, ни строк баланса.
    assert (await session.execute(select(StockTransaction))).scalars().all() == []
    assert await _balance_rows(session, product) == []


async def test_adjustment_rejects_non_positive_quantity_and_unknown_ids(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Ноль/минус и чужие product/location → 422, с признаком в payload или без."""
    product = await _make_product(session)
    location = await _make_location(session)
    await _register_operations(session, location, ["SAW"])
    await session.commit()

    zero = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, quantity=0, completed_operations=["SAW"]),
    )
    assert zero.status_code == 422, zero.text

    unknown_product = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, product_id=999_999, completed_operations=["SAW"]),
    )
    assert unknown_product.status_code == 422, unknown_product.text
    assert "product_id" in unknown_product.json()["detail"]

    unknown_location = await client.post(
        "/api/stock/adjustment",
        json=_payload(product, location, location_id=999_999, completed_operations=["SAW"]),
    )
    assert unknown_location.status_code == 422, unknown_location.text
    assert "location_id" in unknown_location.json()["detail"]

    assert (await session.execute(select(StockTransaction))).scalars().all() == []
