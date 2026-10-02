"""Импорт справочника: размерность 1D/2D/3D в маппинге колонок (#87).

Контракт, который защищают тесты:

- колонка «Размерность» разбирается в состояние размерности, а значения 2D/3D
  едут в `product_dimensions` (`default_value`), а не в `product_lengths`;
- ссылка на несуществующее измерение — ошибка строки с номером строки и SKU, а
  не молчаливое сохранение;
- чужая колонка размерности (высота у 2D, толщина у 3D, габарит у 1D) — ошибка;
- существующие 1D-конфигурации продолжают работать как раньше;
- связи неразмерных типов (weight) при смене размерности не трогаются;
- колонка «Кол-во на подвесе» для 2D/3D не применяется.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from app.api.deps import get_current_user
from app.main import app
from app.models.dimension import DimensionType, ProductDimension
from app.models.product import (
    DimensionState,
    Product,
    ProductLength,
    ProductType,
)
from app.models.user import User, UserRole
from app.services.catalog_excel_import import (
    TEMPLATE_HEADERS,
    ParsedCatalogRow,
    parse_catalog_excel,
    validate_row_counts,
)
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PREVIEW_URL = "/api/catalog-import/preview-excel"
APPLY_URL = "/api/catalog-import/apply-excel"
EXPORT_URL = "/api/catalog-import/export-excel"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

NEW_HEADERS = ("Размерность", "Ширина, мм", "Толщина, мм", "Высота, мм")


def _xlsx_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(list(TEMPLATE_HEADERS))
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(**kwargs) -> list:
    """Строка файла по именам полей; порядок берётся из шаблона."""
    values: dict[str, object] = dict.fromkeys(TEMPLATE_HEADERS, "")
    aliases = {
        "sku": "Артикул",
        "name": "Наименование",
        "notes": "Примечания",
        "lengths": "Длины, мм",
        "perimeter": "Периметр, мм",
        "mount_width": "Габарит, мм",
        "quantities": "Кол-во на подвесе",
        "skip_shot": "Не дробеструится",
        "laminated": "Ламируется",
        "partners": "Парный профиль",
        "raw_lengths": "Сырьевые длины, мм",
        "dimension_state": "Размерность",
        "width_mm": "Ширина, мм",
        "thickness_mm": "Толщина, мм",
        "height_mm": "Высота, мм",
    }
    for key, value in kwargs.items():
        values[aliases.get(key, key)] = value
    return [values[header] for header in TEMPLATE_HEADERS]

@pytest.fixture(autouse=True)
async def _admin():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, username="admin", role=UserRole.admin, section_id=None, is_active=True
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _seed_dimension_types(session: AsyncSession) -> None:
    for code in ("length_mm", "width_mm", "thickness_mm", "height_mm", "weight_kg"):
        session.add(DimensionType(code=code, name=code, unit="мм", value_type="number"))
    await session.flush()


async def _make_product(
    session: AsyncSession, *, sku: str, lengths: list[float] | None = None, **attrs
) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.component,
        unit="шт",
        is_active=True,
    )
    for key, value in attrs.items():
        setattr(product, key, value)
    session.add(product)
    await session.flush()
    for length in lengths or []:
        session.add(ProductLength(product_id=product.id, length_mm=length))
    await session.flush()
    return product


async def _upload(client: AsyncClient, url: str, rows: list[list]):
    return await client.post(
        url, files={"file": ("catalog.xlsx", _xlsx_bytes(rows), XLSX_MIME)}
    )


async def _dimension_values(session: AsyncSession, product_id: int) -> dict[str, float | None]:
    rows = (
        await session.execute(
            select(ProductDimension, DimensionType.code)
            .join(DimensionType, ProductDimension.dimension_type_id == DimensionType.id)
            .where(ProductDimension.product_id == product_id)
        )
    ).all()
    return {code: link.default_value for link, code in rows}


async def _lengths(session: AsyncSession, product_id: int) -> list[float]:
    return sorted(
        (await session.scalars(
            select(ProductLength.length_mm).where(ProductLength.product_id == product_id)
        )).all()
    )


# ─── шаблон ──────────────────────────────────────────────────────────────────


def test_template_carries_dimension_columns() -> None:
    assert all(header in TEMPLATE_HEADERS for header in NEW_HEADERS)


# ─── разбор файла ────────────────────────────────────────────────────────────


def test_parses_2d_row() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="SHEET-1", lengths="2500", dimension_state="2D", width_mm=1350, thickness_mm=4)]),
        "catalog.xlsx",
    )

    assert errors == []
    assert rows[0].fields["dimension_state"] == "area"
    assert rows[0].fields["width_mm"] == 1350
    assert rows[0].fields["thickness_mm"] == 4


def test_parses_3d_row_in_any_case() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="BLOCK-1", lengths=200, dimension_state="3д", width_mm=100, height_mm=50)]),
        "catalog.xlsx",
    )

    assert errors == []
    assert rows[0].fields["dimension_state"] == "volume"
    assert rows[0].fields["height_mm"] == 50


def test_unknown_dimension_token_is_row_error() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="BAD-1", lengths=100, dimension_state="4D")]),
        "catalog.xlsx",
    )

    assert rows == []
    assert errors == [
        {"row": 2, "sku": "BAD-1", "message": "Размерность: ожидается 1D, 2D или 3D, получено «4D»"}
    ]


def _row_of(**fields) -> ParsedCatalogRow:
    return ParsedCatalogRow(row=2, sku="SHEET-2", fields=fields)


def test_2d_requires_thickness_only_when_card_has_none() -> None:
    """Обязательность полей 2D живёт там, где видно заведённое значение.

    Парсер отвергнуть строку не может: пустая ячейка при partial update — это
    «не трогаем», и у артикула с уже заведённой толщиной такая строка обязана
    пройти. Поэтому проверка достаётся слою, который видит карточку.
    """
    row = _row_of(dimension_state="area", lengths_mm=[2500.0], width_mm=1350.0)

    fresh = validate_row_counts(row, None, "length", {})
    existing = validate_row_counts(
        row, None, "area", {"length_mm": 2500.0, "thickness_mm": 4.0}
    )

    assert any("Толщина, мм: обязательно для размерности 2D" in message for message in fresh)
    assert existing == []


def test_2d_requires_length_from_card_or_row() -> None:
    row = _row_of(dimension_state="area", width_mm=1350.0, thickness_mm=4.0)

    without_length = validate_row_counts(row, None, "length", {})
    with_length = validate_row_counts(row, None, "area", {"length_mm": 2500.0})

    assert any("Длины, мм: обязательно для размерности 2D" in message for message in without_length)
    assert with_length == []


def test_2d_rejects_height_column() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="SHEET-3", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4, height_mm=10)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("Высота, мм не заполняется для 2D" in error["message"] for error in errors)


def test_3d_rejects_thickness_column() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="BLOCK-2", lengths=200, dimension_state="3D", width_mm=100, height_mm=50, thickness_mm=5)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("Толщина, мм не заполняется для 3D" in error["message"] for error in errors)


def test_2d_requires_exactly_one_length() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="SHEET-4", lengths="2500, 2700", dimension_state="2D", width_mm=1350, thickness_mm=4)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("ожидается ровно одно значение, получено 2" in error["message"] for error in errors)


def test_dimension_column_without_state_is_error() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="SHEET-6", lengths=2500, width_mm=1350)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("«Размерность»" in error["message"] for error in errors)


def test_linear_row_rejects_dimension_columns() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="BAR-1", lengths=2500, dimension_state="1D", width_mm=1350)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("не заполняются для линейных" in error["message"] for error in errors)


def test_plain_1d_row_parses_as_before() -> None:
    """Существующие 1D-конфигурации не должны почувствовать новых колонок."""
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="BAR-2", lengths="2500, 2700", quantities="48, , 48")]),
        "catalog.xlsx",
    )

    assert errors == []
    assert "dimension_state" not in rows[0].fields
    assert rows[0].fields["lengths_mm"] == [2500, 2700]
    assert rows[0].fields["quantities"] == [48, None, 48]


def test_negative_dimension_value_is_row_error() -> None:
    rows, errors, _ = parse_catalog_excel(
        _xlsx_bytes([_row(sku="SHEET-7", lengths=2500, dimension_state="2D", width_mm=-5, thickness_mm=4)]),
        "catalog.xlsx",
    )

    assert rows == []
    assert any("Ширина, мм" in error["message"] and "> 0" in error["message"] for error in errors)


# ─── apply: создание ─────────────────────────────────────────────────────────


async def test_apply_creates_2d_product_with_dimension_links(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_dimension_types(session)

    response = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-NEW", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    assert response.status_code == 200, response.text
    product = await session.scalar(select(Product).where(Product.sku == "SHEET-NEW"))
    assert product is not None
    assert product.dimension_state == DimensionState.area
    assert await _dimension_values(session, product.id) == {
        "length_mm": 2500.0,
        "width_mm": 1350.0,
        "thickness_mm": 4.0,
    }
    # Длина 2D-артикула живёт в размерности, а не в реестре длин.
    assert await _lengths(session, product.id) == []


async def test_apply_creates_3d_product(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_dimension_types(session)

    response = await _upload(client, APPLY_URL, [
        _row(sku="BLOCK-NEW", lengths=200, dimension_state="3D", width_mm=100, height_mm=50)
    ])

    assert response.status_code == 200, response.text
    product = await session.scalar(select(Product).where(Product.sku == "BLOCK-NEW"))
    assert product is not None
    assert product.dimension_state == DimensionState.volume
    assert await _dimension_values(session, product.id) == {
        "length_mm": 200.0,
        "width_mm": 100.0,
        "height_mm": 50.0,
    }


async def test_apply_creates_plain_product_as_1d(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await _upload(client, APPLY_URL, [_row(sku="BAR-NEW", lengths="2500, 2700")])

    assert response.status_code == 200, response.text
    product = await session.scalar(select(Product).where(Product.sku == "BAR-NEW"))
    assert product is not None
    assert product.dimension_state == DimensionState.length
    assert await _lengths(session, product.id) == [2500.0, 2700.0]


async def test_hanger_quantity_not_applied_for_2d(
    client: AsyncClient, session: AsyncSession
) -> None:
    """У 2D/3D нормы подвеса не настраиваются (ADR-0012) — колонка игнорируется."""
    await _seed_dimension_types(session)

    response = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-QPH", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4, quantities=30)
    ])

    assert response.status_code == 200, response.text
    product = await session.scalar(select(Product).where(Product.sku == "SHEET-QPH"))
    assert product is not None
    assert product.quantity_per_hanger in (None, {})


# ─── apply: обновление ───────────────────────────────────────────────────────


async def test_apply_switches_1d_to_2d_and_keeps_weight_link(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_dimension_types(session)
    product = await _make_product(session, sku="SHEET-UPD", lengths=[2500])
    weight_type = await session.scalar(
        select(DimensionType).where(DimensionType.code == "weight_kg")
    )
    session.add(ProductDimension(product_id=product.id, dimension_type_id=weight_type.id))
    await session.flush()

    response = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-UPD", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    assert response.status_code == 200, response.text
    await session.refresh(product)
    assert product.dimension_state == DimensionState.area
    values = await _dimension_values(session, product.id)
    assert values["width_mm"] == 1350.0
    assert values["thickness_mm"] == 4.0
    # Связь неразмерного типа переживает смену размерности.
    assert "weight_kg" in values
    assert await _lengths(session, product.id) == []


async def test_apply_2d_updates_only_given_dimension(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Partial update: пустая ячейка размерности не трогает заведённое значение."""
    await _seed_dimension_types(session)
    first = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-PART", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])
    assert first.status_code == 200, first.text

    second = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-PART", dimension_state="2D", width_mm=1400)
    ])

    assert second.status_code == 200, second.text
    product = await session.scalar(select(Product).where(Product.sku == "SHEET-PART"))
    assert product is not None
    values = await _dimension_values(session, product.id)
    assert values["width_mm"] == 1400.0
    assert values["thickness_mm"] == 4.0
    assert values["length_mm"] == 2500.0


async def test_apply_switches_2d_to_3d_dropping_thickness_link(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_dimension_types(session)
    await _upload(client, APPLY_URL, [
        _row(sku="SHEET-SW", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    response = await _upload(client, APPLY_URL, [
        _row(sku="SHEET-SW", lengths=2500, dimension_state="3D", width_mm=1350, height_mm=10)
    ])

    assert response.status_code == 200, response.text
    product = await session.scalar(select(Product).where(Product.sku == "SHEET-SW"))
    assert product is not None
    values = await _dimension_values(session, product.id)
    assert values["height_mm"] == 10.0
    assert "thickness_mm" not in values


# ─── preview ─────────────────────────────────────────────────────────────────


async def test_preview_shows_dimension_state_and_values(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_dimension_types(session)

    response = await _upload(client, PREVIEW_URL, [
        _row(sku="SHEET-PRE", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["dimension_state"] == "area"
    assert item["dimension_label"] == "2D"
    assert item["dimensions"] == {"length_mm": 2500.0, "width_mm": 1350.0, "thickness_mm": 4.0}
    assert item["action"] == "create"


async def test_preview_reports_dimension_change_as_update(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Смена 1D → 2D — самостоятельное изменение, иначе строка ушла бы в skip."""
    await _seed_dimension_types(session)
    await _make_product(session, sku="BAR-TO-2D", lengths=[2500])

    response = await _upload(client, PREVIEW_URL, [
        _row(sku="BAR-TO-2D", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stats"]["update"] == 1
    assert body["items"][0]["action"] == "update"


async def test_preview_reports_row_error_for_foreign_dimension_column(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await _upload(client, PREVIEW_URL, [
        _row(sku="BAD-PRE", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4, height_mm=10)
    ])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["stats"]["errors"] == 1
    assert any("Высота, мм" in error["message"] for error in body["errors"])

async def test_export_writes_dimension_columns_for_round_trip(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Выгрузка 2D-артикула должна содержать оси: файл идёт обратно в импорт."""
    await _seed_dimension_types(session)
    await _upload(client, APPLY_URL, [
        _row(sku="SHEET-EXP", lengths=2500, dimension_state="2D", width_mm=1350, thickness_mm=4)
    ])

    response = await client.get(EXPORT_URL)

    assert response.status_code == 200, response.text
    wb = load_workbook(BytesIO(response.content))
    header = [cell.value for cell in wb.active[1]]
    row = dict(zip(header, [cell.value for cell in wb.active[2]], strict=True))
    assert row["Размерность"] == "2D"
    assert row["Ширина, мм"] == 1350
    assert row["Толщина, мм"] == 4
    assert row["Высота, мм"] is None
    assert row["Длины, мм"] == 2500

    reimported = await _upload(client, PREVIEW_URL, [[row.get(header) for header in header]])
    assert reimported.status_code == 200, reimported.text
    assert reimported.json()["stats"]["update"] == 0
