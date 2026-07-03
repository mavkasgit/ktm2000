"""Тесты импорта остатков из Excel (Remainders Import).

Проверяют:
- Preview парсинга Excel (с валидацией, без записи в БД).
- Применение импорта (MANUAL_IN транзакции, обновление баланса).
- Пропуск невалидных строк (skip_invalid).
- Атомарный откат при skip_invalid=False.
- Очистку существующих остатков (clear_existing).
- Качество (quality_state) в создаваемых транзакциях.
- Обработку неизвестного SKU.
- Скачивание шаблона.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section
from app.models.user import User, UserRole
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService

pytestmark = pytest.mark.asyncio


# ─── Helpers ───────────────────────────────────────────────────────────────────


async def _make_product(
    session: AsyncSession,
    sku: str = "IMP-PROD",
    name: str | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, code: str = "STOCK-IMP") -> Section:
    section = Section(
        code=code,
        name=code,
        kind="raw_stock",
        type="raw_stock",
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


def _make_excel(
    rows: list[tuple[str | None, object, str | None]],
    headers: tuple[str, str, str] = ("SKU", "Количество", "Комментарий"),
) -> BytesIO:
    """Create an .xlsx file in memory with the given header and data rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Остатки"
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


async def _make_stock_balance(
    session: AsyncSession,
    product_id: int,
    location_id: int,
    qty: Decimal,
    quality_state: QualityState = QualityState.GOOD,
) -> None:
    """Create a stock balance directly via StockCommandService."""
    svc = StockCommandService()
    cmd = StockCommand(
        product_id=product_id,
        to_location_id=location_id,
        quantity=qty,
        reason=Reason.MANUAL_IN,
        quality_state=quality_state,
        created_by=1,
        created_by_user_name="system",
    )
    await svc.record(session, cmd)
    await session.commit()


# ─── Tests: Preview ────────────────────────────────────────────────────────────


async def test_preview_remainders_excel_happy_path(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """POST /import/remainders/preview возвращает items и summary."""
    product = await _make_product(session, "PREV-001", "Тестовый продукт 1")
    product2 = await _make_product(session, "PREV-002", "Тестовый продукт 2")
    location = await _make_location(session, "PREVIEW-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("PREV-001", 10, "коммент1"),
        ("PREV-002", 20, None),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders/preview",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "quality_state": "good",
            "sheet_index": "0",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["sheet_name"] == "Остатки"
    assert body["total_rows"] == 3  # header + 2 data rows
    assert body["summary"]["total"] == 2
    assert body["summary"]["valid"] == 2
    assert body["summary"]["invalid"] == 0
    assert body["summary"]["quantity_total"] == 30.0

    items = body["items"]
    assert len(items) == 2

    # Item 1
    assert items[0]["sku"] == "PREV-001"
    assert items[0]["quantity"] == 10.0
    assert items[0]["product_id"] == product.id
    assert items[0]["product_name"] == "Тестовый продукт 1"
    assert items[0]["status"] == "valid"
    assert items[0]["comment"] == "коммент1"
    assert items[0]["errors"] == []

    # Item 2
    assert items[1]["sku"] == "PREV-002"
    assert items[1]["quantity"] == 20.0
    assert items[1]["product_id"] == product2.id
    assert items[1]["status"] == "valid"
    assert items[1]["comment"] is None


async def test_preview_remainders_excel_unknown_sku(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Неизвестный SKU → invalid строка в preview."""
    location = await _make_location(session, "PREVIEW-UNK")
    await session.commit()

    excel_buf = _make_excel([
        ("UNKNOWN-SKU", 5, None),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders/preview",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"location_id": str(location.id), "sheet_index": "0"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["summary"]["total"] == 1
    assert body["summary"]["valid"] == 0
    assert body["summary"]["invalid"] == 1
    items = body["items"]
    assert items[0]["status"] == "invalid"
    assert any("not found" in e for e in items[0]["errors"])


# ─── Tests: Import ─────────────────────────────────────────────────────────────


async def test_import_remainders_excel_creates_manual_in_transactions(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Happy path: создаются StockTransaction с reason=MANUAL_IN и баланс обновлён."""
    product = await _make_product(session, "IMPORT-001")
    location = await _make_location(session, "IMPORT-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("IMPORT-001", 100, "тестовый импорт"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "quality_state": "good",
            "sheet_index": "0",
            "skip_invalid": "true",
            "clear_existing": "false",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1
    assert len(body["transaction_ids"]) == 1

    # Проверяем транзакцию в БД
    tx_id = body["transaction_ids"][0]
    tx = await session.get(StockTransaction, tx_id)
    assert tx is not None
    assert tx.product_id == product.id
    assert tx.to_location_id == location.id
    assert tx.from_location_id is None
    assert tx.reason == Reason.MANUAL_IN
    assert float(tx.quantity) == 100.0
    assert tx.source_ref == "import_remainders_excel"

    # Проверяем баланс
    balance = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == location.id,
        )
    )
    bal = balance.scalar_one_or_none()
    assert bal is not None
    assert float(bal.balance_qty) == 100.0


async def test_import_remainders_excel_skip_invalid(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """1 валидная + 1 невалидная (пустой SKU) → imported_count=1, errors есть."""
    product = await _make_product(session, "SKIP-VALID")
    location = await _make_location(session, "SKIP-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("SKIP-VALID", 50, "ок"),
        ("", 10, "нет SKU"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "skip_invalid": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1
    assert len(body["errors"]) == 1  # одна ошибка о пустом SKU
    assert "SKU is empty" in body["errors"][0]

    # Только 1 транзакция создана
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 1


async def test_import_remainders_excel_atomic_fail(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """skip_invalid=False с невалидной строкой → success=false, ничего не записано."""
    product = await _make_product(session, "ATOMIC-OK")
    location = await _make_location(session, "ATOMIC-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("ATOMIC-OK", 30, "хорошая строка"),
        ("", None, "плохая строка"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "skip_invalid": "false",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["imported_count"] == 0
    assert len(body["transaction_ids"]) == 0
    assert len(body["errors"]) > 0

    # Ни одной транзакции не создано
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 0


async def test_import_remainders_excel_clear_existing(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """clear_existing=True: существующие остатки обнуляются, потом импортируются новые."""
    product = await _make_product(session, "CLEAR-001")
    location = await _make_location(session, "CLEAR-LOC")
    await session.commit()

    # Создаём существующий остаток 200 шт
    await _make_stock_balance(session, product.id, location.id, Decimal("200"))

    # Проверяем что баланс есть
    bal_before = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == location.id,
        )
    )
    assert bal_before.scalar_one_or_none() is not None

    excel_buf = _make_excel([
        ("CLEAR-001", 50, "новый импорт"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "clear_existing": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1

    # Всего 3 транзакции: 1 (initial _make_stock_balance) +
    # 1 ADJUSTMENT_OUT (clear_existing) + 1 MANUAL_IN (import).
    txs = (await session.execute(select(StockTransaction))).scalars().all()
    assert len(txs) == 3

    reasons = [tx.reason for tx in txs]
    assert Reason.ADJUSTMENT_OUT in reasons
    assert Reason.MANUAL_IN in reasons

    adjust_tx = next(tx for tx in txs if tx.reason == Reason.ADJUSTMENT_OUT)
    assert float(adjust_tx.quantity) == 200.0
    assert adjust_tx.from_location_id == location.id

    manual_txs = [tx for tx in txs if tx.reason == Reason.MANUAL_IN]
    assert len(manual_txs) == 2  # 1 from _make_stock_balance + 1 from import
    import_manual = next(tx for tx in manual_txs if tx.source_ref == "import_remainders_excel")
    assert float(import_manual.quantity) == 50.0

    # Финальный баланс = 50
    final_balance = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == location.id,
        )
    )
    bal = final_balance.scalar_one_or_none()
    assert bal is not None
    assert float(bal.balance_qty) == 50.0


async def test_import_remainders_excel_quality_state(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """quality_state=SCRAP → StockBalance создан с quality_state=SCRAP."""
    product = await _make_product(session, "SCRAP-001")
    location = await _make_location(session, "SCRAP-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("SCRAP-001", 15, "брак"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "quality_state": "scrap",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1

    # Проверяем транзакцию
    tx = (await session.execute(select(StockTransaction))).scalar_one()
    assert tx.to_quality_state == QualityState.SCRAP

    # Проверяем баланс по scrap
    balance = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == location.id,
            StockBalance.quality_state == QualityState.SCRAP,
        )
    )
    bal = balance.scalar_one_or_none()
    assert bal is not None
    assert float(bal.balance_qty) == 15.0

    # Баланса по good быть не должно
    good_balance = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == location.id,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )
    assert good_balance.scalar_one_or_none() is None


async def test_import_remainders_excel_unknown_sku(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """SKU которого нет в БД → invalid."""
    location = await _make_location(session, "UNK-LOC")
    await session.commit()

    excel_buf = _make_excel([
        ("NONEXISTENT-SKU", 99, "нет такого продукта"),
    ])

    resp = await client.post(
        "/api/v2/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "location_id": str(location.id),
            "skip_invalid": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # skip_invalid=True → success, но imported_count=0
    assert body["success"] is True
    assert body["imported_count"] == 0
    assert len(body["errors"]) == 1
    assert "not found" in body["errors"][0]


async def test_download_remainders_template(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """GET /import/remainders/template возвращает валидный .xlsx файл."""
    location = await _make_location(session, "TMPL-LOC")
    await session.commit()

    resp = await client.get(
        "/api/v2/stock/import/remainders/template",
        params={"location_id": location.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "filename*" in resp.headers.get("content-disposition", "")

    # Проверяем что это валидный xlsx
    content = resp.content
    assert len(content) > 100
    # Проверяем, что можно открыть openpyxl
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(content))
    assert wb.active is not None
    ws = wb.active
    # 1 строка-справочник + заголовок + 2 примера = 4 строки
    assert ws.max_row == 4
    # Первая строка — справочник операций
    assert "Доступные операции:" in str(ws.cell(1, 1).value)
    assert ws.cell(2, 1).value == "SKU / Артикул"


async def test_download_remainders_template_includes_operations(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """GET /import/remainders/template содержит строку 'Доступные операции:' с именами операций."""
    location = await _make_location(session, "TMPL-OPS-LOC")
    await session.commit()

    resp = await client.get(
        "/api/v2/stock/import/remainders/template",
        params={"location_id": location.id},
    )
    assert resp.status_code == 200, resp.text

    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(resp.content))
    ws = wb.active
    assert ws is not None

    first_cell = str(ws.cell(1, 1).value or "")
    assert first_cell.startswith("Доступные операции:")

    # Должно быть хотя бы одно имя операции (из БД или fallback)
    # Fallback: ["Дробеструй", "Сверловка"]
    assert "Дробеструй" in first_cell or "Сверловка" in first_cell
