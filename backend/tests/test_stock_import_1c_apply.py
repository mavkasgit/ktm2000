"""Применение импорта остатков 1С (ОСВ): коды, история, откат (#459).

Спека: ``docs/stock-import-1c-spec.md`` §3 п.4/5/11/12, §5.3–§5.4, §7, §9,
§11, §13.

Проверяют:
- успешный импорт ОСВ через API: проводки, изученные ``product_1c_codes``,
  ``stock_import_rows.source_code`` / ``source_quantity_m``;
- комментарий проводки — ровно ``Импорт остатков из 1С``, без чисел;
- повторный импорт того же файла: без дублей кодов, батчи разные;
- конфликт кода и группы: строка invalid, код не перепривязан, остальные
  строки идут по ``skip_invalid``;
- ручной шаблон оставляет поля источника ``NULL`` и прежний комментарий;
- история отдаёт код и метры; откат батча возвращает остатки;
- ``assert_no_invariants_violations`` после импорта и после отката.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from app.models import (
    Product,
    Product1CCode,
    Product1CSkipped,
    ProductLength,
    ProductType,
    Section,
)
from app.models.action_journal import Action
from app.reversal.service import reversal_service
from app.stock.import_1c_osv import _norm_cell
from app.stock.import_history import get_batch, get_batch_rows, mark_rolled_back
from app.stock.import_models import StockImportRow
from app.stock.import_service import RemainderItem, apply_remainders_import
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_integrity_invariants import assert_no_invariants_violations

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Двухстрочная шапка реальной выгрузки: «Конечное сальдо / Количество» —
# колонка 10 (индекс с нуля), как в #458.
OSV_HEADER = (
    "Код",
    "Наименование ТМЦ",
    "Ед. изм.",
    "Цена за ед.",
    "Начальное сальдо",
    None,
    "Оборот по дебету",
    None,
    "Оборот по кредиту",
    None,
    "Конечное сальдо",
    None,
)
OSV_SUBHEADER = (
    None,
    None,
    None,
    None,
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
)
SECTION_HEADER = "Завод КТМ СКЛАД СЫРОЙ"

OSV_TRANSACTION_COMMENT = "Импорт остатков из 1С"
MANUAL_TRANSACTION_COMMENT = "Импорт остатков из Excel"


# ─── Синтетические xlsx ───────────────────────────────────────────────────────


def _osv_row(code: object, name: object, unit: object, quantity: object) -> list:
    return [code, name, unit, None, None, None, None, None, None, None, quantity, None]


def _make_sheets(sheets: list[tuple[str, list[list]]]) -> bytes:
    wb = Workbook()
    for position, (name, rows) in enumerate(sheets):
        ws = wb.active if position == 0 else wb.create_sheet()
        ws.title = name
        for row in rows:
            ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_osv_workbook(data_rows: list[list]) -> bytes:
    rows = [
        ["Оборотно-сальдовая ведомость по счету 10"],
        [],
        [SECTION_HEADER],
        [],
        [],
        [],
        [],
        list(OSV_HEADER),
        list(OSV_SUBHEADER),
        *data_rows,
    ]
    return _make_sheets([("Склад сырой", rows)])


def _post_import(client: AsyncClient, section: Section, content: bytes, **data: str):
    payload = {
        "location_id": str(section.id),
        "sheet_index": "0",
        "skip_invalid": "true",
        **data,
    }
    return client.post(
        "/api/stock/import/remainders",
        files={"file": ("osv.xlsx", content, XLSX_MIME)},
        data=payload,
    )


# ─── Справочник ───────────────────────────────────────────────────────────────


async def _make_product(
    session: AsyncSession,
    sku: str,
    *,
    name: str | None = None,
    lengths: list[tuple[float, float | None, bool]] | None = None,
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
    for length_mm, raw_length_mm, is_primary in lengths or []:
        session.add(
            ProductLength(
                product_id=product.id,
                length_mm=length_mm,
                raw_length_mm=raw_length_mm,
                is_primary=is_primary,
            )
        )
    await session.flush()
    return product


async def _make_section(session: AsyncSession, code: str, name: str) -> Section:
    section = Section(
        code=code, name=name, type="raw_stock", is_active=True, sort_order=0
    )
    session.add(section)
    await session.flush()
    return section


async def _codes(session: AsyncSession) -> dict[str, Product1CCode]:
    rows = (await session.scalars(select(Product1CCode))).all()
    return {row.code: row for row in rows}


async def _transactions(session: AsyncSession, action_id: int) -> list[StockTransaction]:
    return list(
        (
            await session.scalars(
                select(StockTransaction).where(StockTransaction.action_id == action_id)
            )
        ).all()
    )


# ─── Импорт через API: проводки, коды, история ────────────────────────────────


async def test_import_osv_creates_transactions_learns_codes_and_writes_history(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Валидные ОСВ-строки: проводки, коды 1С, код/метры в истории, комментарий."""
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    meters_product = await _make_product(
        session,
        "OSV-APPLY-M",
        name="Профиль П-образный",
        # 2,75 м в наименовании — сырьевая длина, учётная нормальная — 2700.
        lengths=[(2700, 2750, True)],
    )
    pieces_product = await _make_product(
        session,
        "OSV-APPLY-PCS",
        name="Кант универсальный",
        lengths=[(2700, None, True)],
    )
    await session.commit()

    content = _make_osv_workbook(
        [
            _osv_row("20933", "Профиль (OSV-APPLY-M) 2,75м", "м", 5084.1),
            # «шт» длинномерного артикула: длина в штуках не пересчитывается и
            # не должна становиться invalid на повторном резолве габаритов.
            _osv_row("22069", "Кант (OSV-APPLY-PCS) 2,7м", "шт", 7),
        ]
    )

    resp = await _post_import(client, section, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 2
    assert body["errors"] == []
    assert body["batch_id"] is not None

    # ── Проводки: комментарий ровно без чисел, штуки — учёт ────────────────
    txs = await _transactions(session, body["action_id"])
    assert len(txs) == 2
    assert {tx.reason for tx in txs} == {Reason.MANUAL_IN}
    assert [tx.comment for tx in txs] == [OSV_TRANSACTION_COMMENT] * 2
    meters_tx = next(tx for tx in txs if tx.quantity == Decimal("1883.0000"))
    assert meters_tx.product_id == meters_product.id

    # ── Изученные коды номенклатуры 1С ────────────────────────────────────
    codes = await _codes(session)
    assert set(codes) == {"20933", "22069"}
    assert codes["20933"].product_id == meters_product.id
    assert codes["22069"].product_id == pieces_product.id
    assert {code.source for code in codes.values()} == {"1c_osv"}
    assert all(code.created_by is not None for code in codes.values())

    # ── История: код и метры источника ───────────────────────────────────
    detail = await client.get(
        f"/api/stock/import/remainders/batches/{body['batch_id']}"
    )
    assert detail.status_code == 200, detail.text
    rows = {row["source_code"]: row for row in detail.json()["rows"]}
    assert set(rows) == {"20933", "22069"}

    meters_row = rows["20933"]
    assert Decimal(meters_row["source_quantity_m"]) == Decimal("5084.1")
    # quantity остаётся штуками: floor(5084,1 / 2,7) = 1883.
    assert Decimal(meters_row["quantity"]) == Decimal(1883)
    assert meters_row["status"] == "valid"
    assert Decimal(meters_row["current_balance"]) == Decimal(1883)

    pieces_row = rows["22069"]
    assert pieces_row["source_quantity_m"] is None
    assert Decimal(pieces_row["quantity"]) == Decimal(7)
    assert pieces_row["status"] == "valid"
    assert Decimal(pieces_row["current_balance"]) == Decimal(7)

    await assert_no_invariants_violations(session, context="osv-apply")


async def test_import_osv_osv_tail_creates_two_positions_with_own_transactions(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Строка с остатком метров: две проводки, две строки истории, откат обеих.

    5,2 м при нормальной 2,5 м — 2 шт × 2,5 м + 1 шт × 0,2 м (#495). Обе
    позиции — обычные строки ledger со своим ``stock_transaction_id``; откат
    батча возвращает оба размера.
    """
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    product = await _make_product(
        session, "OSV-TAIL", name="Плинтус алюм.", lengths=[(2500, None, True)]
    )
    session.add(Product1CCode(product_id=product.id, code="36905"))
    await session.commit()

    content = _make_osv_workbook(
        [_osv_row("36905", "КП-3690-05 ПФ 2,5м", "м", 5.2)]
    )
    resp = await _post_import(client, section, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 2
    assert body["errors"] == []

    txs = await _transactions(session, body["action_id"])
    assert len(txs) == 2
    by_length = {
        (tx.dimensions or {}).get("length_mm"): tx
        for tx in txs
        if tx.product_id == product.id
    }
    assert set(by_length) == {2500, 200}
    assert by_length[2500].quantity == Decimal("2.0000")
    assert by_length[200].quantity == Decimal("1.0000")
    assert {tx.comment for tx in txs} == {OSV_TRANSACTION_COMMENT}

    # ── История: две строки одного номера, у каждой своя проводка ─────────
    rows = (
        await session.scalars(
            select(StockImportRow).where(
                StockImportRow.batch_id == body["batch_id"]
            )
        )
    ).all()
    assert len(rows) == 2
    assert {row.source_row_number for row in rows} == {10}
    assert all(row.status == "valid" for row in rows)
    assert {row.stock_transaction_id for row in rows} == {
        by_length[2500].id,
        by_length[200].id,
    }
    by_dimensions = {
        (row.dimensions or {}).get("length_mm"): row for row in rows
    }
    # Метры источника — только у основной позиции.
    assert by_dimensions[2500].source_quantity_m == Decimal("5.2")
    assert by_dimensions[200].source_quantity_m is None
    assert len(by_dimensions[2500].warnings) == 1
    assert by_dimensions[2500].warnings == by_dimensions[200].warnings

    # ── Остатки: два размера, дробных штук нет ────────────────────────────
    balances = (
        await session.scalars(
            select(StockBalance).where(
                StockBalance.product_id == product.id,
                StockBalance.location_id == section.id,
                StockBalance.quality_state == QualityState.GOOD.value,
            )
        )
    ).all()
    by_balance_dims = {
        (balance.dimensions or {}).get("length_mm"): balance.balance_qty
        for balance in balances
    }
    assert by_balance_dims == {
        2500: Decimal("2.0000"),
        200: Decimal("1.0000"),
    }

    # ── Откат возвращает оба размера ──────────────────────────────────────
    action = await session.get(Action, body["action_id"])
    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester"
    )
    await mark_rolled_back(
        session, await get_batch(session, body["batch_id"]), user=None
    )
    await session.commit()

    remaining = (
        await session.scalars(
            select(StockBalance).where(
                StockBalance.product_id == product.id,
                StockBalance.location_id == section.id,
                StockBalance.quality_state == QualityState.GOOD.value,
            )
        )
    ).all()
    assert all(balance.balance_qty == 0 for balance in remaining)

    await assert_no_invariants_violations(session, context="osv-tail-rollback")


async def test_reimport_same_osv_file_keeps_single_code_and_new_batches(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Повторный импорт того же файла: код не дублируется, батчи разные."""
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    product = await _make_product(
        session,
        "OSV-REPEAT",
        name="Профиль П-образный",
        lengths=[(2700, 2750, True)],
    )
    await session.commit()
    content = _make_osv_workbook(
        [_osv_row("20933", "Профиль (OSV-REPEAT) 2,75м", "м", 5400)]
    )

    first = await _post_import(client, section, content)
    assert first.status_code == 200, first.text
    second = await _post_import(client, section, content)
    assert second.status_code == 200, second.text

    first_body, second_body = first.json(), second.json()
    assert first_body["success"] is True and second_body["success"] is True
    assert first_body["imported_count"] == second_body["imported_count"] == 1
    assert first_body["batch_id"] != second_body["batch_id"]

    codes = await _codes(session)
    assert list(codes) == ["20933"]
    assert codes["20933"].product_id == product.id

    await assert_no_invariants_violations(session, context="osv-reimport")


# ─── Конфликт кода и группы (сервисный шов) ───────────────────────────────────


async def test_code_conflict_marks_row_invalid_and_never_rebinds(
    session: AsyncSession,
) -> None:
    """Код привязан к группе A, строка указывает на B: invalid, код не меняется,
    остальные строки применяются по ``skip_invalid``."""
    section = await _make_section(session, "OSV-CONFLICT-LOC", "Склад конфликтов")
    bound = await _make_product(session, "OSV-CONFLICT-A")
    other = await _make_product(session, "OSV-CONFLICT-B")
    session.add(Product1CCode(product_id=bound.id, code="16944"))
    await session.commit()

    def _item(row: int, code: str) -> RemainderItem:
        return RemainderItem(
            source_row_number=row,
            sku=other.sku,
            quantity=5.0,
            comment=None,
            product_id=other.id,
            product_name=other.name,
            status="valid",
            errors=[],
            raw_values=[],
            source_code=code,
            source_quantity_m=12.5,
        )

    result = await apply_remainders_import(
        session,
        section.id,
        [_item(10, "16944"), _item(11, "17777")],
        user=None,
    )
    await session.commit()

    assert result.success is True
    assert result.imported_count == 1
    batch = await get_batch(session, result.batch_id)
    assert batch.skipped_rows == 1

    rows = {row.source_code: row for row in await get_batch_rows(session, batch.id)}
    conflict = rows["16944"]
    assert conflict.status == "invalid"
    assert conflict.source_code == "16944"
    assert conflict.source_quantity_m == Decimal("12.5")
    assert (
        "Код 16944 привязан к OSV-CONFLICT-A, в наименовании OSV-CONFLICT-B"
        in conflict.errors
    )

    codes = await _codes(session)
    assert codes["16944"].product_id == bound.id  # не перепривязан
    assert codes["17777"].product_id == other.id  # свободный код изучен

    txs = await _transactions(session, result.action_id)
    assert len(txs) == 1
    assert txs[0].product_id == other.id

    await assert_no_invariants_violations(session, context="osv-conflict")


async def test_same_free_code_for_two_products_in_file_is_conflict(
    session: AsyncSession,
) -> None:
    """Один свободный код у двух артикулов файла: обе строки invalid, код не создан."""
    from app.stock.import_service import _resolve_1c_code_bindings

    first = await _make_product(session, "OSV-DUP-A")
    second = await _make_product(session, "OSV-DUP-B")

    def _item(row: int, product: Product) -> RemainderItem:
        return RemainderItem(
            source_row_number=row,
            sku=product.sku,
            quantity=5.0,
            comment=None,
            product_id=product.id,
            product_name=product.name,
            status="valid",
            errors=[],
            raw_values=[],
            source_code="24555",
        )

    items = [_item(10, first), _item(11, second)]

    pending = await _resolve_1c_code_bindings(session, items, None)

    assert pending == []
    assert [item.status for item in items] == ["invalid", "invalid"]
    for item in items:
        assert item.errors == [
            "Код 24555 встречается у разных артикулов в файле: OSV-DUP-A, OSV-DUP-B"
        ]
    assert (
        await session.scalar(
            select(Product1CCode).where(Product1CCode.code == "24555")
        )
        is None
    )


async def test_aborted_import_does_not_learn_codes(session: AsyncSession) -> None:
    """``skip_invalid=False`` с конфликтом кода отменяет батч — и изучение
    свободного кода отменённых строк тоже: иначе отклонённый импорт менял бы
    справочник."""
    section = await _make_section(session, "OSV-ABORT-LOC", "Склад отмены")
    bound = await _make_product(session, "OSV-ABORT-A")
    other = await _make_product(session, "OSV-ABORT-B")
    session.add(Product1CCode(product_id=bound.id, code="16944"))
    await session.commit()

    def _item(row: int, code: str) -> RemainderItem:
        return RemainderItem(
            source_row_number=row,
            sku=other.sku,
            quantity=5.0,
            comment=None,
            product_id=other.id,
            product_name=other.name,
            status="valid",
            errors=[],
            raw_values=[],
            source_code=code,
        )

    result = await apply_remainders_import(
        session,
        section.id,
        [_item(10, "16944"), _item(11, "18888")],
        user=None,
        skip_invalid=False,
    )
    await session.commit()

    assert result.success is False
    codes = await _codes(session)
    assert list(codes) == ["16944"]
    assert codes["16944"].product_id == bound.id
    assert await session.scalar(select(StockTransaction).limit(1)) is None



# ─── Ручной шаблон не затронут ────────────────────────────────────────────────


async def test_manual_template_keeps_source_fields_null(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Ручной шаблон: ``source_code``/``source_quantity_m`` = NULL, комментарий
    прежний — ОСВ-поля не протекают в обычный импорт."""
    section = await _make_section(session, "OSV-MANUAL-LOC", "Ручной участок")
    product = await _make_product(session, "OSV-MANUAL")
    await session.commit()

    content = _make_sheets(
        [
            (
                "Импорт остатков",
                [
                    ["Артикул", "Кол-во", "Статус качества", "Операции", "Участок"],
                    [product.sku, 4, "Годный", "", section.name],
                ],
            )
        ]
    )

    resp = await _post_import(client, section, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1

    txs = await _transactions(session, body["action_id"])
    assert [tx.comment for tx in txs] == [MANUAL_TRANSACTION_COMMENT]

    rows = await get_batch_rows(session, body["batch_id"])
    assert len(rows) == 1
    assert rows[0].source_code is None
    assert rows[0].source_quantity_m is None
    assert rows[0].status == "valid"

    assert await _codes(session) == {}


# ─── Откат батча ОСВ ──────────────────────────────────────────────────────────


async def test_rollback_osv_import_returns_balances_and_keeps_invariants(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Откат батча ОСВ возвращает остатки и не ломает ledger; коды остаются."""
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    product = await _make_product(
        session,
        "OSV-ROLLBACK",
        name="Профиль П-образный",
        lengths=[(2700, 2750, True)],
    )
    await session.commit()

    content = _make_osv_workbook(
        [_osv_row("30123", "Профиль (OSV-ROLLBACK) 2,75м", "м", 5084.1)]
    )
    resp = await _post_import(client, section, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported_count"] == 1

    balance = await session.scalar(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == section.id,
            StockBalance.quality_state == QualityState.GOOD.value,
        )
    )
    assert balance is not None and balance.balance_qty == Decimal("1883.0000")

    action = await session.get(Action, body["action_id"])
    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester"
    )
    await mark_rolled_back(
        session, await get_batch(session, body["batch_id"]), user=None
    )
    await session.commit()

    await assert_no_invariants_violations(session, context="osv-rollback")

    remaining = await session.scalar(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == section.id,
            StockBalance.quality_state == QualityState.GOOD.value,
        )
    )
    assert remaining is None or remaining.balance_qty == 0

    batch = await get_batch(session, body["batch_id"])
    assert batch.rolled_back_at is not None
    # Код номенклатуры — факт справочника, а не остатка: откат его не трогает.
    assert list(await _codes(session)) == ["30123"]


# ─── Реестр исключений (#464) ─────────────────────────────────────────────────


async def test_import_osv_registry_skipped_rows_not_imported_and_not_errors(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Разобранная строка не грузится, не считается ошибкой и видна в счётчиках.

    Батч фиксирует вердикты импорта: строка валидна и залита, а исключённая
    реестром — только в ``skipped_rows``/``summary.skipped_registry``, потому
    что это решение каталога, а не дефект файла.
    """
    section = await _make_section(session, "RAW_STOCK", "Склад сырья")
    product = await _make_product(
        session, "OSV-REG-OK", name="Кант универсальный", lengths=[(2700, None, True)]
    )
    session.add(
        Product1CSkipped(
            code="19001",
            name_norm=_norm_cell("Упаковка пакет 40*60"),
            reason="not_mes",
            note="упаковка",
            decided_by="test",
        )
    )
    await session.commit()

    content = _make_osv_workbook(
        [
            _osv_row("20933", "Кант (OSV-REG-OK) 2,7м", "м", 2700),
            # Код не привязан к артикулу, но записан в реестре.
            _osv_row("19001", "Упаковка пакет 40*60", "шт", 10),
        ]
    )

    resp = await _post_import(client, section, content)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1
    assert body["errors"] == []

    txs = await _transactions(session, body["action_id"])
    assert [tx.product_id for tx in txs] == [product.id]

    batch = await get_batch(session, body["batch_id"])
    assert batch.total_rows == 2
    assert batch.imported_rows == 1
    assert batch.skipped_rows == 1
    assert batch.summary["skipped_registry"] == 1

    # Вердиктов импорта у исключённой строки нет: её не рассматривали.
    rows = await get_batch_rows(session, body["batch_id"])
    assert [row.source_code for row in rows] == ["20933"]
    assert rows[0].status == "valid"

    await assert_no_invariants_violations(session, context="osv-registry-skip")
