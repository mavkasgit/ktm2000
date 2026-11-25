"""Коды номенклатуры 1С и поля источника в строках импорта (#455).

Схема хранения кодов ОСВ: у артикула может быть несколько кодов 1С, код
уникален между артикулами, удаление артикула уносит его коды. Строка импорта
помнит исходный код и метры источника (``source_code`` /
``source_quantity_m``), но это история: она не мешает удалить артикул.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from app.models import (
    Product,
    Product1CCode,
    ProductType,
    StockImportBatch,
    StockImportRow,
    StockImportRowStatus,
)
from app.models.action_journal import Action
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def _product(sku: str) -> Product:
    return Product(sku=sku, name=sku, type=ProductType.component, unit="pcs", is_active=True)


async def _import_row(
    session,
    *,
    product_id: int | None = None,
    source_code: str | None = None,
    source_quantity_m: Decimal | None = None,
) -> StockImportRow:
    action = Action(action_type="import_remainders")
    session.add(action)
    await session.flush()
    batch = StockImportBatch(action_id=action.id)
    session.add(batch)
    await session.flush()
    row = StockImportRow(
        batch_id=batch.id,
        source_row_number=5,
        sku="",
        product_id=product_id,
        status=StockImportRowStatus.VALID,
        source_code=source_code,
        source_quantity_m=source_quantity_m,
    )
    session.add(row)
    await session.flush()
    return row


async def test_product_keeps_multiple_1c_codes_and_deleting_it_cascades(session) -> None:
    product = _product("MIG-1C-ONE")
    session.add(product)
    await session.flush()
    session.add_all(
        [
            Product1CCode(product_id=product.id, code="20933"),
            Product1CCode(product_id=product.id, code="22069"),
        ]
    )
    await session.commit()

    codes = (
        await session.scalars(
            select(Product1CCode).where(Product1CCode.product_id == product.id)
        )
    ).all()
    assert sorted(code.code for code in codes) == ["20933", "22069"]
    assert {code.source for code in codes} == {"1c_osv"}
    assert all(code.created_at is not None for code in codes)

    await session.delete(product)
    await session.commit()

    left = (
        await session.scalars(
            select(Product1CCode).where(Product1CCode.product_id == product.id)
        )
    ).all()
    assert left == []


async def test_1c_code_is_unique_across_products(session) -> None:
    first = _product("MIG-1C-FIRST")
    second = _product("MIG-1C-SECOND")
    session.add_all([first, second])
    await session.flush()
    session.add(Product1CCode(product_id=first.id, code="SHARED-CODE"))
    await session.commit()

    session.add(Product1CCode(product_id=second.id, code="SHARED-CODE"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_stock_import_row_stores_1c_source_fields_and_allows_null(session) -> None:
    product = _product("MIG-1C-ROW")
    session.add(product)
    await session.flush()
    row = await _import_row(
        session,
        product_id=product.id,
        source_code="20933",
        source_quantity_m=Decimal("27.0000"),
    )
    legacy = await _import_row(session)
    await session.commit()

    loaded = await session.get(StockImportRow, row.id)
    assert loaded.source_code == "20933"
    assert loaded.source_quantity_m == Decimal("27.0000")
    assert loaded.quantity is None

    legacy_loaded = await session.get(StockImportRow, legacy.id)
    assert legacy_loaded.source_code is None
    assert legacy_loaded.source_quantity_m is None


async def test_import_row_does_not_block_product_deletion(session) -> None:
    product = _product("MIG-1C-HISTORY")
    session.add(product)
    await session.flush()
    row = await _import_row(
        session,
        product_id=product.id,
        source_code="10926",
        source_quantity_m=Decimal("12.5000"),
    )
    await session.commit()
    row_id = row.id

    await session.delete(product)
    await session.commit()

    # Новая сессия в реальном запросе увидела бы NULL; в тесте сбрасываем
    # identity map, иначе session.get вернёт закэшированный объект.
    session.expire_all()
    reloaded = await session.get(StockImportRow, row_id)
    assert reloaded is not None
    assert reloaded.product_id is None
    assert reloaded.source_code == "10926"
    assert reloaded.source_quantity_m == Decimal("12.5000")
