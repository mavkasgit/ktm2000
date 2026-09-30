"""Ось «пройденные операции» в ключе остатка (ADR-0055).

Регрессия на конкретный дефект: импорт 8888 шт. с операцией «окно» на «Склад
сырья» давал одну строку остатка `13388` вместо двух — `8888` (прошёл окно) и
`4500` (без операций). Признак из колонки «Операции» уезжал в текст комментария
проводки и в ключ баланса не попадал, поэтому материал с разными операциями
сливался в одну сумму.

Проверяем:
- две строки файла одного артикула с разными операциями дают две строки остатка;
- операции пишутся в `stock_transactions.completed_operations` (не в комментарий);
- признак `NULL` и пустой список — разные группы остатка;
- расход списывает строку с совпавшим признаком, а не соседнюю группу;
- инвариант S1 (остаток == net по ledger) держится на раздельноcящихся группах.
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
from app.models.route import SectionOperation
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService, StockValidationError
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# created_by — NOT NULL на уровне БД; тесту не нужен реальный пользователь.
ACTOR_ID = 1

HEADERS = (
    "Артикул",
    "Количество",
    "Статус качества",
    "Операции",
    "Участок",
    "Комментарий",
    "Длина",
)


async def _make_product(session: AsyncSession, sku: str) -> Product:
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


async def _make_location(session: AsyncSession, code: str) -> Section:
    section = Section(code=code, name=code, type="raw_stock", is_active=True, sort_order=0)
    session.add(section)
    await session.flush()
    return section


async def _make_operation(session: AsyncSession, section: Section, code: str, name: str) -> None:
    session.add(
        SectionOperation(
            section_id=section.id,
            operation_code=code,
            operation_name=name,
            operation_type="production",
            is_significant=True,
            sort_order=0,
        )
    )
    await session.flush()


def _make_excel(rows: list[tuple]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Остатки"
    ws.append(list(HEADERS))
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


async def _balances(
    session: AsyncSession, product: Product, location: Section
) -> list[StockBalance]:
    return (
        await session.scalars(
            select(StockBalance).where(
                StockBalance.product_id == product.id,
                StockBalance.location_id == location.id,
            )
        )
    ).all()


async def test_import_splits_balance_by_completed_operations(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Строки с разными «Операциями» — разные строки остатка, не одна сумма."""
    location = await _make_location(session, "OPS-RAW")
    await _make_operation(session, location, "WINDOW", "Окно")
    product = await _make_product(session, "OPS-460")
    await session.commit()

    excel_buf = _make_excel([
        ("OPS-460", 8888, "Годный", "Окно", location.name, None, "2,7"),
        ("OPS-460", 4500, "Годный", None, location.name, None, "2,7"),
    ])
    resp = await client.post(
        "/api/stock/import/remainders",
        files={"file": ("test.xlsx", excel_buf, XLSX_MIME)},
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
    assert body["imported_count"] == 2

    # Признак попал в проводку, а не растворился в комментарии.
    txs = (
        await session.scalars(
            select(StockTransaction).where(
                StockTransaction.id.in_(body["transaction_ids"])
            )
        )
    ).all()
    ops_by_qty = {float(tx.quantity): tx.completed_operations for tx in txs}
    assert ops_by_qty[8888.0] == ["WINDOW"]
    assert ops_by_qty[4500.0] is None

    # Две строки остатка, а не одна на 13388.
    balances = await _balances(session, product, location)
    assert len(balances) == 2, [
        (b.completed_operations, float(b.balance_qty)) for b in balances
    ]
    by_ops = {
        tuple(b.completed_operations) if b.completed_operations else None:
            float(b.balance_qty)
        for b in balances
    }
    assert by_ops == {("WINDOW",): 8888.0, None: 4500.0}

    await assert_no_invariants_violations(session, context="ops-axis-import")


async def test_null_and_empty_operations_are_different_balance_rows(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`NULL` («операции вне маршрута») и `[]` («операций не было») — разные группы."""
    location = await _make_location(session, "OPS-NULLEMPTY")
    product = await _make_product(session, "OPS-NE")
    await session.commit()

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            quality_state=QualityState.GOOD,
            completed_operations=None,
            created_by=ACTOR_ID,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("30"),
            reason=Reason.MANUAL_IN,
            quality_state=QualityState.GOOD,
            completed_operations=[],
            created_by=ACTOR_ID,
        ),
    )
    await session.commit()

    balances = await _balances(session, product, location)
    assert len(balances) == 2
    assert {float(b.balance_qty) for b in balances} == {100.0, 30.0}
    assert sorted(
        b.completed_operations is None for b in balances
    ) == [False, True]


async def test_write_off_touches_only_matching_operations_row(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Расход уменьшает строку с совпавшим признаком, соседнюю группу не трогает."""
    location = await _make_location(session, "OPS-WRITEOFF")
    await _make_operation(session, location, "SHOT", "Дробеструй")
    product = await _make_product(session, "OPS-WO")
    await session.commit()

    # Куда уходит списанное: участок должен отличаться от исходного —
    # net-zero проводка (from == to) баланс не двигает и проверку проходит вхолостую.
    sink = await _make_location(session, "OPS-WRITEOFF-SINK")

    svc = StockCommandService()
    for qty, ops in ((Decimal("500"), ["SHOT"]), (Decimal("200"), None)):
        await svc.record(
            session,
            StockCommand(
                product_id=product.id,
                to_location_id=location.id,
                quantity=qty,
                reason=Reason.MANUAL_IN,
                quality_state=QualityState.GOOD,
                completed_operations=ops,
                created_by=ACTOR_ID,
            ),
        )
    await session.commit()

    # Успешный расход против известной группы.
    await svc.record(
        session,
        StockCommand(
            product_id=product.id,
            from_location_id=location.id,
            to_location_id=sink.id,
            quantity=Decimal("100"),
            reason=Reason.ADJUSTMENT_OUT,
            quality_state=QualityState.GOOD,
            completed_operations=["SHOT"],
            created_by=ACTOR_ID,
        ),
    )
    await session.commit()

    balances = {
        (tuple(b.completed_operations) if b.completed_operations else None): float(
            b.balance_qty
        )
        for b in await _balances(session, product, location)
    }
    assert balances == {("SHOT",): 400.0, None: 200.0}


async def test_write_off_without_matching_operations_row_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Остаток есть, но не в той группе — расход отклоняется, а не идёт «хоть откуда»."""
    location = await _make_location(session, "OPS-NOGROUP")
    await _make_operation(session, location, "SHOT", "Дробеструй")
    sink = await _make_location(session, "OPS-NOGROUP-SINK")
    product = await _make_product(session, "OPS-NG")
    await session.commit()

    # Дальше будет rollback, после которого ORM-объекты протухают: их id держим
    # обычными числами, иначе проверка результата дёрнет ленивую перезагрузку.
    product_id, location_id, sink_id = product.id, location.id, sink.id

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=Decimal("500"),
            reason=Reason.MANUAL_IN,
            quality_state=QualityState.GOOD,
            completed_operations=["SHOT"],
            created_by=ACTOR_ID,
        ),
    )
    await session.commit()

    # Признак расхода — NULL, а весь остаток лежит в группе ["SHOT"].
    with pytest.raises(StockValidationError, match="completed_operations"):
        await svc.record(
            session,
            StockCommand(
                product_id=product_id,
                from_location_id=location_id,
                to_location_id=sink_id,
                quantity=Decimal("10"),
                reason=Reason.ADJUSTMENT_OUT,
                quality_state=QualityState.GOOD,
                completed_operations=None,
                created_by=ACTOR_ID,
            ),
        )
    await session.rollback()

    # Читаем скаляром: обращение к атрибутам протухших ORM-объектов дёрнуло бы
    # ленивую перезагрузку вне greenlet-контекста.
    rows = (
        await session.execute(
            select(StockBalance.balance_qty, StockBalance.completed_operations).where(
                StockBalance.product_id == product_id,
                StockBalance.location_id == location_id,
            )
        )
    ).all()
    assert [(float(qty), ops) for qty, ops in rows] == [(500.0, ["SHOT"])]
