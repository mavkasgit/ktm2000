"""Импорт/выгрузка справочника сырья из Excel (#63): preview/apply/template/export-excel."""

from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.main import app
from app.models.product import (
    DimensionState,
    ProcessingFlag,
    Product,
    ProductLength,
    ProductPair,
    ProductProcessingFlag,
    ProductType,
)
from app.models.user import User, UserRole
from app.services.catalog_excel_import import (
    TEMPLATE_HEADERS,
    parse_catalog_excel,
)

PREVIEW_URL = "/api/catalog-import/preview-excel"
APPLY_URL = "/api/catalog-import/apply-excel"
TEMPLATE_URL = "/api/catalog-import/template-excel"
EXPORT_URL = "/api/catalog-import/export-excel"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_bytes(rows: list[list], headers: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers if headers is not None else list(TEMPLATE_HEADERS))
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(**kwargs) -> list:
    """Строка файла по именованным полям (остальные колонки пустые)."""
    # Колонки шаблона = TEMPLATE_HEADERS (Парный профиль импортируется;
    # размерность всегда 1D, фото заполняется руками).
    values: dict[str, object] = {field: "" for field in (
        "sku", "name", "notes", "lengths", "perimeter", "mount_width",
        "quantities", "skip_shot", "laminated", "aliases", "partners",
    )}
    values.update(kwargs)
    return [
        values["sku"], values["name"], values["perimeter"], values["mount_width"],
        values["lengths"], values["quantities"], values["notes"],
        values["skip_shot"], values["laminated"], values["aliases"],
        values["partners"],
    ]


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str | None = None,
    lengths: list[float] | None = None,
    aliases: list[str] | None = None,
    **attrs,
) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.component,
        unit="шт",
        is_active=True,
        aliases=aliases or [],
    )
    for key, value in attrs.items():
        setattr(product, key, value)
    session.add(product)
    await session.flush()
    for length in lengths or []:
        session.add(ProductLength(product_id=product.id, length_mm=length))
    await session.flush()
    return product


async def _upload(client: AsyncClient, url: str, content: bytes, filename: str = "catalog.xlsx"):
    return await client.post(url, files={"file": (filename, content, XLSX_MIME)})


async def _product_lengths(session: AsyncSession, product_id: int) -> list[float]:
    rows = await session.scalars(
        select(ProductLength.length_mm).where(ProductLength.product_id == product_id)
    )
    return sorted(rows.all())


# ─── template-excel ──────────────────────────────────────────────────────────


async def test_template_excel_returns_full_reference_headers(client: AsyncClient) -> None:
    resp = await client.get(TEMPLATE_URL)
    assert resp.status_code == 200, resp.text
    wb = load_workbook(BytesIO(resp.content))
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert headers == list(TEMPLATE_HEADERS)
    assert "Активен" not in headers and "Статус" not in headers


# ─── preview-excel ───────────────────────────────────────────────────────────


async def test_preview_excel_rejects_wrong_extension(client: AsyncClient) -> None:
    resp = await _upload(client, PREVIEW_URL, b"not a workbook", filename="catalog.txt")
    assert resp.status_code == 400


async def test_preview_excel_create_update_skip_actions(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(
        session, sku="ЮП-100", name="Старое имя", perimeter_mm=50.0, lengths=[2780.0]
    )
    content = _xlsx_bytes([
        _row(sku="ЮП-100", perimeter="64,2"),  # update
        _row(sku="ЮП-200", name="Новый"),  # create
        _row(sku="ЮП-300"),  # create без данных
    ])
    resp = await _upload(client, PREVIEW_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actions = {item["sku"]: item["action"] for item in body["items"]}
    assert actions == {"ЮП-100": "update", "ЮП-200": "create", "ЮП-300": "create"}
    assert body["stats"]["total"] == 3
    assert body["stats"]["create"] == 2
    assert body["stats"]["update"] == 1
    assert body["stats"]["skip"] == 0
    assert body["errors"] == []
    empty_create = next(item for item in body["items"] if item["sku"] == "ЮП-300")
    assert empty_create["warnings"]  # создание без данных — с warning


async def test_preview_excel_skip_when_nothing_changes(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-100", perimeter_mm=64.2)
    content = _xlsx_bytes([_row(sku="ЮП-100", perimeter="64,2")])
    resp = await _upload(client, PREVIEW_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"][0]["action"] == "skip"
    assert body["stats"]["skip"] == 1


async def test_preview_excel_row_errors_reported_and_rows_skipped(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([
        _row(sku="BAD-PERIM", perimeter="0"),
        _row(sku="BAD-PERIM-JUNK", perimeter="мусор"),
        _row(sku="BAD-MOUNT", mount_width="-5"),
        _row(sku="BAD-COUNT", lengths="2780, 3000", quantities="72"),
        _row(sku="BAD-QTY", lengths="2780", quantities="12,5"),
        _row(sku="BAD-BOOL", skip_shot="может быть"),
        _row(sku="OK", perimeter="10"),
    ])
    resp = await _upload(client, PREVIEW_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    error_skus = {err["sku"] for err in body["errors"]}
    assert error_skus == {"BAD-PERIM", "BAD-PERIM-JUNK", "BAD-MOUNT", "BAD-COUNT", "BAD-QTY", "BAD-BOOL"}
    for err in body["errors"]:
        assert err["row"] >= 2
        assert err["message"]
    assert {item["sku"] for item in body["items"]} == {"OK"}


async def test_preview_excel_lookup_by_primary_sku_only(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-100", aliases=["АЛИАС-1"])
    content = _xlsx_bytes([_row(sku="АЛИАС-1", perimeter="10")])
    resp = await _upload(client, PREVIEW_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Алиас в колонке «Артикул» → новый продукт, поиск по алиасам не идёт
    assert body["items"][0]["action"] == "create"


async def test_preview_excel_duplicate_sku_in_file_is_error(client: AsyncClient) -> None:
    content = _xlsx_bytes([
        _row(sku="ДУБЛЬ", perimeter="10"),
        _row(sku="ДУБЛЬ", perimeter="20"),
    ])
    resp = await _upload(client, PREVIEW_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["sku"] == "ДУБЛЬ"
    assert len(body["items"]) == 1


# ─── apply-excel ─────────────────────────────────────────────────────────────


async def test_apply_excel_partial_update_touches_only_filled_cells(
    client: AsyncClient, session: AsyncSession
) -> None:
    product = await _make_product(
        session,
        sku="ЮП-100",
        name="Исходное имя",
        color="серебро",
        lengths=[2780.0],
        perimeter_mm=50.0,
    )
    product.quantity_per_hanger = {"2780": {"auto": None, "manual": 55}}
    await session.flush()

    content = _xlsx_bytes([
        _row(sku="ЮП-100", perimeter="64,2", lengths="2780, 3000", quantities="72, 65"),
    ])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 1
    assert body["imported"] == 0
    assert body["errors"] == []

    await session.refresh(product)
    assert product.name == "Исходное имя"  # пустая ячейка не тронута
    assert product.color == "серебро"
    assert product.perimeter_mm == pytest.approx(64.2)
    assert await _product_lengths(session, product.id) == [2780.0, 3000.0]
    # quantity_per_hanger заменяется целиком, параллельно длинам
    assert product.quantity_per_hanger_by_length == {
        "2780": {"auto": None, "manual": 72},
        "3000": {"auto": None, "manual": 65},
    }


async def test_apply_excel_quantities_replace_whole_dict(
    client: AsyncClient, session: AsyncSession
) -> None:
    product = await _make_product(session, sku="ЮП-100", lengths=[2780.0, 3000.0])
    product.quantity_per_hanger = {
        "2780": {"auto": None, "manual": 55},
        "3000": {"auto": None, "manual": 50},
    }
    await session.flush()

    content = _xlsx_bytes([_row(sku="ЮП-100", lengths="3000", quantities="10")])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    await session.refresh(product)
    assert product.quantity_per_hanger_by_length == {"3000": {"auto": None, "manual": 10}}


async def test_apply_excel_quantities_for_existing_lengths_when_lengths_empty(
    client: AsyncClient, session: AsyncSession
) -> None:
    product = await _make_product(session, sku="ЮП-100", lengths=[2780.0, 3000.0])
    content = _xlsx_bytes([_row(sku="ЮП-100", quantities="72, 65")])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    await session.refresh(product)
    assert product.quantity_per_hanger_by_length == {
        "2780": {"auto": None, "manual": 72},
        "3000": {"auto": None, "manual": 65},
    }


async def test_apply_excel_creates_component_active(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([
        _row(
            sku="ЮП-900",
            name="Профиль 900",
            lengths="2780, 3000",
            perimeter="64,2",
            mount_width="19,35",
            quantities="72, 65",
            skip_shot="нет",
            laminated="да",
            aliases="ЭВ-1; ЭВ-2",
            notes="прим",
        ),
    ])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 1
    assert body["errors"] == []

    product = await session.scalar(select(Product).where(Product.sku == "ЮП-900"))
    assert product is not None
    assert product.type == ProductType.component
    assert product.is_active is True
    assert product.name == "Профиль 900"
    assert product.perimeter_mm == pytest.approx(64.2)
    assert product.mount_width_mm == pytest.approx(19.35)
    assert await _product_lengths(session, product.id) == [2780.0, 3000.0]
    # Импорт пишет ручные значения; периметр И габарит в строке → режим auto,
    # авто досчитано движком (#127), ручное сохранено отдельно.
    assert product.hanger_mode == "auto"
    assert product.quantity_per_hanger_by_length == {
        "2780": {"auto": 72, "manual": 72},
        "3000": {"auto": 67, "manual": 65},
    }
    assert sorted(product.aliases) == ["ЭВ-1", "ЭВ-2"]
    # Эквиваленты двунаправленные
    ev1 = await session.scalar(select(Product).where(Product.sku == "ЭВ-1"))
    assert ev1 is None  # неизвестные эквиваленты не создают продукты
    assert product.notes == "прим"


async def test_apply_excel_booleans_sync_flags(
    client: AsyncClient, session: AsyncSession
) -> None:
    flag_shot = ProcessingFlag(code="skip_shot_blast", name="Не дробеструится")
    flag_lam = ProcessingFlag(code="is_laminated", name="Ламируется")
    session.add_all([flag_shot, flag_lam])
    await session.flush()

    product = await _make_product(session, sku="ЮП-100")
    session.add(ProductProcessingFlag(product_id=product.id, flag_id=flag_shot.id))
    await session.flush()

    content = _xlsx_bytes([_row(sku="ЮП-100", skip_shot="нет", laminated="да")])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text

    await session.refresh(product, attribute_names=["processing_flags"])
    codes = {f.code for f in product.processing_flags}
    assert codes == {"is_laminated"}


async def test_apply_excel_aliases_bidirectional(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЭВ-1")
    content = _xlsx_bytes([_row(sku="ЮП-100", aliases="ЭВ-1")])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text

    target = await session.scalar(select(Product).where(Product.sku == "ЭВ-1"))
    assert "ЮП-100" in (target.aliases or [])


async def test_apply_excel_counts_and_error_rows_skipped(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-100", perimeter_mm=64.2)
    content = _xlsx_bytes([
        _row(sku="ЮП-100"),  # skip — ничего не меняется (кроме форсов type/active, которые уже верны)
        _row(sku="ЮП-200", perimeter="10"),  # imported
        _row(sku="ЮП-300", perimeter="-1"),  # ошибка строки
    ])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert body["updated"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["sku"] == "ЮП-300"
    assert await session.scalar(select(Product).where(Product.sku == "ЮП-300")) is None


async def test_apply_excel_empty_row_creates_with_warning(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([_row(sku="ЮП-ПУСТО")])
    preview = await _upload(client, PREVIEW_URL, content)
    assert preview.status_code == 200
    item = preview.json()["items"][0]
    assert item["action"] == "create"
    assert item["warnings"]
    assert item["draft"] is True

    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-ПУСТО"))
    assert product is not None
    assert product.type == ProductType.component
    # Черновик без длин — неактивен, пока не допишут длины.
    assert product.is_active is False


async def test_apply_excel_requires_edit_references_role(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Запись — по правам editReferences (#154): operator — 403, preview — пускают."""
    content = _xlsx_bytes([_row(sku="ЮП-РОЛИ", perimeter="10")])
    user = User(username="catalog_operator", full_name="operator", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        forbidden = await _upload(client, APPLY_URL, content)
        assert forbidden.status_code == 403
        allowed = await _upload(client, PREVIEW_URL, content)
        assert allowed.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ─── Черновики и нормы без длин (#177 Q2/Q3) ──────────────────────────────────


async def test_preview_draft_single_qty_no_lengths(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([_row(sku="ЮП-ЧЕРН", quantities="35")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert body["errors"] == []
    item = body["items"][0]
    assert item["action"] == "create"
    assert item["draft"] is True


async def test_apply_draft_creates_inactive_with_legacy_norm(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q3: норма без длин черновик не активирует. Q2: сама норма — legacy-скаляр."""
    content = _xlsx_bytes([_row(sku="ЮП-ЧЕРН", quantities="35", name="Черновик")])
    resp = await _upload(client, APPLY_URL, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-ЧЕРН"))
    assert product is not None
    assert product.is_active is False
    assert await _product_lengths(session, product.id) == []
    # Норма хранится скаляром и раскроется в per-length, когда появятся длины.
    assert product.attributes["quantity_per_hanger"] == {"auto": None, "manual": 35}
    assert product.quantity_per_hanger == 35
    assert product.quantity_per_hanger_by_length is None


async def test_apply_norm_without_lengths_keeps_draft_inactive_and_round_trips(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q3/Q2/Q11: строка с нормой без длин не активирует черновик и не теряет норму."""
    product = await _make_product(session, sku="ЮП-ЧЕРНОВИК", is_active=False)
    content = _xlsx_bytes([_row(sku="ЮП-ЧЕРНОВИК", quantities="22")])

    body = (await _upload(client, APPLY_URL, content)).json()

    assert body["errors"] == []
    assert body["updated"] == 1
    await session.refresh(product)
    assert product.is_active is False
    assert product.attributes["quantity_per_hanger"] == {"auto": None, "manual": 22}
    assert product.quantity_per_hanger == 22

    # Round-trip: норма без длин возвращается в файл числом при пустых «Длинах».
    _, by_sku = await _export(client)
    assert by_sku["ЮП-ЧЕРНОВИК"]["Длины, мм"] is None
    assert by_sku["ЮП-ЧЕРНОВИК"]["Кол-во на подвесе"] == 22


async def test_apply_row_with_length_activates_draft(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q3 положительный контроль: строка с длиной активирует артикул как раньше."""
    product = await _make_product(session, sku="ЮП-ЧЕРНОВИК-ДЛИНА", is_active=False)
    content = _xlsx_bytes([_row(sku="ЮП-ЧЕРНОВИК-ДЛИНА", lengths="2750")])

    body = (await _upload(client, APPLY_URL, content)).json()

    assert body["errors"] == []
    assert body["updated"] == 1
    await session.refresh(product)
    assert product.is_active is True
    assert await _product_lengths(session, product.id) == [2750.0]


async def test_apply_multi_qty_no_lengths_is_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q2 граница: две нормы при пустых «Длинах» — ошибка строки для нового и существующего артикула."""
    await _make_product(session, sku="ЮП-ЧЕРН3")
    content = _xlsx_bytes([
        _row(sku="ЮП-ЧЕРН2", quantities="35, 36"),  # нет в БД
        _row(sku="ЮП-ЧЕРН3", quantities="35, 36"),  # есть в БД, длин нет
    ])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 2
    assert sorted(err["sku"] for err in body["errors"]) == ["ЮП-ЧЕРН2", "ЮП-ЧЕРН3"]
    for err in body["errors"]:
        assert "Кол-во на подвесе" in err["message"] and "Длины, мм" in err["message"]
    assert body["items"] == []

    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["imported"] == 0
    assert resp.json()["updated"] == 0
    assert await session.scalar(select(Product).where(Product.sku == "ЮП-ЧЕРН2")) is None
    existing = await session.scalar(select(Product).where(Product.sku == "ЮП-ЧЕРН3"))
    assert (existing.attributes or {}).get("quantity_per_hanger") is None


# ─── Композит «45+10» не поддерживается ───────────────────────────────────────


async def test_composite_without_partner_is_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([_row(sku="ЮП-К1", quantities="45+10")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 1
    assert "не поддерживается" in body["errors"][0]["message"]
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["imported"] == 0
    assert await session.scalar(select(Product).where(Product.sku == "ЮП-К1")) is None


async def test_composite_with_partner_is_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-П1", lengths=[2750.0])
    content = _xlsx_bytes([_row(sku="ЮП-К4", quantities="45+10", partners="ЮП-П1")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 1
    assert "не поддерживается" in body["errors"][0]["message"]


# ─── Пары ──────────────────────────────────────────────────────────────────────


async def test_unknown_partner_blocks_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    content = _xlsx_bytes([_row(sku="ЮП-ПАР", quantities="30", partners="ЮП-НЕТ")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 1
    assert "не найден" in body["errors"][0]["message"]
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["imported"] == 0
    assert await session.scalar(select(Product).where(Product.sku == "ЮП-ПАР")) is None


async def test_pair_qty_suffix_is_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-П1", lengths=[2750.0])
    content = _xlsx_bytes([_row(
        sku="ЮП-ПАР2", name="Парный", lengths="2750",
        quantities="30", partners="ЮП-П1, 24",
    )])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 1
    assert "pairs-API" in body["errors"][0]["message"]
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["imported"] == 0
    assert await session.scalar(select(Product).where(Product.sku == "ЮП-ПАР2")) is None


async def test_pair_created_without_norm(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-П1", lengths=[2750.0])
    content = _xlsx_bytes([_row(
        sku="ЮП-ПАР2", name="Парный", lengths="2750",
        quantities="30", partners="ЮП-П1",
    )])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert body["errors"] == [], body["errors"]
    assert body["items"][0]["pairs"] == [{"sku": "ЮП-П1", "create": True}]
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["pairs_created"] == 1
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-ПАР2"))
    partner = await session.scalar(select(Product).where(Product.sku == "ЮП-П1"))
    pair = await session.scalar(
        select(ProductPair).where(
            ProductPair.product_a_id == min(product.id, partner.id),
            ProductPair.product_b_id == max(product.id, partner.id),
        )
    )
    assert pair is not None
    assert pair.quantity_per_hanger == {}


async def test_existing_pair_not_duplicated(
    client: AsyncClient, session: AsyncSession
) -> None:
    p1 = await _make_product(session, sku="ЮП-П1", lengths=[2750.0])
    p2 = await _make_product(session, sku="ЮП-П2", lengths=[2750.0])
    session.add(ProductPair(
        product_a_id=min(p1.id, p2.id),
        product_b_id=max(p1.id, p2.id),
        quantity_per_hanger={},
    ))
    await session.flush()
    content = _xlsx_bytes([_row(sku="ЮП-П1", partners="ЮП-П2")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert body["errors"] == []
    assert body["items"][0]["pairs"] == [{"sku": "ЮП-П2", "create": False}]
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["pairs_created"] == 0


async def test_update_pair_error_defers_only_pair(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, sku="ЮП-СУЩ", lengths=[2750.0])
    content = _xlsx_bytes([_row(sku="ЮП-СУЩ", name="Новое имя", partners="ЮП-НЕТ")])
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert len(body["errors"]) == 1
    assert "не найден" in body["errors"][0]["message"]
    assert body["items"][0]["action"] == "update"
    assert body["items"][0]["pairs"] == []
    resp = await _upload(client, APPLY_URL, content)
    assert resp.json()["updated"] == 1
    assert resp.json()["pairs_created"] == 0
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-СУЩ"))
    assert product.name == "Новое имя"


async def test_legacy_dimension_photo_columns_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = list(TEMPLATE_HEADERS) + ["Размерность", "Фото"]
    content = _xlsx_bytes(
        [_row(sku="ЮП-ЛГ") + ["2D", "products/ЮП-ЛГ_full.jpg"]],
        headers=headers,
    )
    body = (await _upload(client, PREVIEW_URL, content)).json()
    assert body["errors"] == []
    assert (await _upload(client, APPLY_URL, content)).json()["imported"] == 1
    product = await session.scalar(select(Product).where(Product.sku == "ЮП-ЛГ"))
    assert product.dimension_state == DimensionState.length
    assert product.photo_full is None


# ─── export-excel ────────────────────────────────────────────────────────────


async def _seed_export_catalog(session: AsyncSession) -> None:
    """Справочник, покрывающий границы формата выгрузки.

    Артикул с одной длиной и ручной нормой (числовые ячейки), артикул с
    тремя длинами и пропущенной средней нормой (пустой сегмент), артикул
    без данных, артикул с флагом/алиасами/фото и пара из двух артикулов,
    артикул с нормой без длин (legacy-скаляр, #177 Q2/Q11) и артикул с
    длинами и без единой нормы (#177 Q11).
    """
    await _make_product(
        session,
        sku="ЮП-ОДИН",
        name="Перила 2780",
        perimeter_mm=64.2,
        mount_width_mm=19.35,
        lengths=[2780.0],
        quantity_per_hanger={"2780": {"auto": None, "manual": 72}},
    )
    await _make_product(
        session,
        sku="ЮП-МНОГО",
        name="Перила 2500/2700/3000",
        lengths=[2500.0, 2700.0, 3000.0],
        quantity_per_hanger={
            "2500": {"auto": None, "manual": 48},
            "2700": {"auto": None, "manual": None},
            "3000": {"auto": None, "manual": 48},
        },
    )
    await _make_product(session, sku="ЮП-БЕЗ-ДАННЫХ")
    # Норма без длин: скаляром, а не dict — setter модели пишет legacy-скаляр
    # {auto: null, manual: 22} именно из int.
    await _make_product(session, sku="ЮП-НОРМА-БЕЗ-ДЛИН", quantity_per_hanger=22)
    await _make_product(session, sku="ЮП-БЕЗ-НОРМ", lengths=[2500.0, 2700.0])
    flagged = await _make_product(
        session,
        sku="ЮП-ФЛАГ",
        name="Перила 2750",
        lengths=[2750.0],
        notes="прим",
        aliases=["ЭВ-2", "ЭВ-1"],
        photo_full="products/ЮП-ФЛАГ_full.jpg",
        quantity_per_hanger={"2750": {"auto": None, "manual": 30}},
    )
    partner = await _make_product(
        session, sku="ЮП-ПАРТНЁР", name="Парный 2750", lengths=[2750.0]
    )

    flag = ProcessingFlag(code="skip_shot_blast", name="Не дробеструится")
    session.add(flag)
    await session.flush()
    session.add(ProductProcessingFlag(product_id=flagged.id, flag_id=flag.id))
    session.add(ProductPair(
        product_a_id=min(flagged.id, partner.id),
        product_b_id=max(flagged.id, partner.id),
        quantity_per_hanger={},
    ))
    await session.flush()


async def _export(client: AsyncClient):
    """GET export-excel → (ответ, строки листа по артикулу)."""
    resp = await client.get(EXPORT_URL)
    assert resp.status_code == 200, resp.text
    sheet = load_workbook(BytesIO(resp.content)).active
    header = [cell.value for cell in sheet[1]]
    by_sku = {
        row[0]: dict(zip(header, row))
        for row in sheet.iter_rows(min_row=2, values_only=True)
    }
    return resp, by_sku


async def test_export_excel_headers_mime_and_filename(client: AsyncClient) -> None:
    resp, _ = await _export(client)
    assert resp.headers["content-type"].startswith(XLSX_MIME)
    assert "final_catalog.xlsx" in resp.headers["content-disposition"]
    sheet = load_workbook(BytesIO(resp.content)).active
    header = [cell.value for cell in sheet[1]]
    # Выгрузка — ровно колонки импорта; «Фото» остаётся только в рабочем файле (#177 Q4/Q12).
    assert header == list(TEMPLATE_HEADERS)
    assert len(header) == 11
    assert "Фото" not in header


async def test_export_excel_single_length_and_norm_are_numbers(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    _, by_sku = await _export(client)
    row = by_sku["ЮП-ОДИН"]
    assert row["Наименование"] == "Перила 2780"
    # Одиночные значения — числа, а не строки: строка «2780» не равна 2780.
    assert row["Длины, мм"] == 2780
    assert row["Кол-во на подвесе"] == 72
    assert row["Периметр, мм"] == pytest.approx(64.2)
    assert row["Габарит, мм"] == pytest.approx(19.35)


async def test_export_excel_multi_lengths_keep_positional_empty_segment(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    _, by_sku = await _export(client)
    row = by_sku["ЮП-МНОГО"]
    assert row["Длины, мм"] == "2500, 2700, 3000"
    # Норма без значения — пустой сегмент; соседние нормы не сдвигаются.
    assert row["Кол-во на подвесе"] == "48, , 48"


async def test_export_excel_product_without_data_has_blank_cells(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    _, by_sku = await _export(client)
    row = by_sku["ЮП-БЕЗ-ДАННЫХ"]
    assert row["Наименование"] == "ЮП-БЕЗ-ДАННЫХ"
    assert row["Длины, мм"] is None
    assert row["Кол-во на подвесе"] is None
    assert not row["Не дробеструится"]
    assert not row["Ламируется"]
    assert not row["Эквиваленты"]
    assert not row["Парный профиль"]
    assert "Фото" not in row


async def test_export_excel_flags_aliases_and_pair_without_photo(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    resp, by_sku = await _export(client)
    row = by_sku["ЮП-ФЛАГ"]
    assert row["Не дробеструится"] == "да"
    assert not row["Ламируется"]
    assert row["Примечания"] == "прим"
    assert set(row["Эквиваленты"].split("; ")) == {"ЭВ-1", "ЭВ-2"}
    # Пара выгружается в обе стороны.
    assert row["Парный профиль"] == "ЮП-ПАРТНЁР"
    assert by_sku["ЮП-ПАРТНЁР"]["Парный профиль"] == "ЮП-ФЛАГ"
    # Фото в БД заполнено, но в выгрузку не уезжает ни колонкой, ни значением (#177 Q4).
    sheet = load_workbook(BytesIO(resp.content)).active
    values = [value for sheet_row in sheet.iter_rows(values_only=True) for value in sheet_row]
    assert "products/ЮП-ФЛАГ_full.jpg" not in values


async def test_export_excel_norm_without_lengths_round_trips_as_number(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q2/Q11: норма без длин выгружается числом в пустых «Длинах» и не теряется."""
    await _seed_export_catalog(session)
    resp, by_sku = await _export(client)
    row = by_sku["ЮП-НОРМА-БЕЗ-ДЛИН"]
    assert row["Длины, мм"] is None
    assert row["Кол-во на подвесе"] == 22  # число: строка «22» не равна 22

    rows, errors, _ = parse_catalog_excel(resp.content, "final_catalog.xlsx")

    assert errors == []
    fields = {parsed.sku: parsed.fields for parsed in rows}["ЮП-НОРМА-БЕЗ-ДЛИН"]
    assert "lengths_mm" not in fields
    assert fields["quantities"] == [22]

    preview = await _upload(client, PREVIEW_URL, resp.content, filename="final_catalog.xlsx")

    body = preview.json()
    assert body["errors"] == []
    item = next(item for item in body["items"] if item["sku"] == "ЮП-НОРМА-БЕЗ-ДЛИН")
    assert item["action"] == "skip"  # норма доехала до файла и не переписывается


async def test_export_excel_lengths_without_norms_leave_cell_empty(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Q11: длин без норм — пустая ячейка, а не «, »: пустые сегменты материализуют записи."""
    await _seed_export_catalog(session)
    resp, by_sku = await _export(client)
    row = by_sku["ЮП-БЕЗ-НОРМ"]
    assert row["Длины, мм"] == "2500, 2700"
    assert row["Кол-во на подвесе"] is None

    rows, errors, _ = parse_catalog_excel(resp.content, "final_catalog.xlsx")

    assert errors == []
    fields = {parsed.sku: parsed.fields for parsed in rows}["ЮП-БЕЗ-НОРМ"]
    assert fields["lengths_mm"] == [2500.0, 2700.0]
    assert "quantities" not in fields

    preview = await _upload(client, PREVIEW_URL, resp.content, filename="final_catalog.xlsx")

    body = preview.json()
    assert body["errors"] == []
    item = next(item for item in body["items"] if item["sku"] == "ЮП-БЕЗ-НОРМ")
    assert item["action"] == "skip"  # «, » здесь дал бы update — правку норм на пустые


async def test_export_excel_rows_round_trip_through_parser(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    resp, _ = await _export(client)

    rows, errors, total = parse_catalog_excel(resp.content, "final_catalog.xlsx")

    assert errors == []
    assert total == 7
    fields = {row.sku: row.fields for row in rows}
    assert set(fields) == {
        "ЮП-ОДИН",
        "ЮП-МНОГО",
        "ЮП-БЕЗ-ДАННЫХ",
        "ЮП-НОРМА-БЕЗ-ДЛИН",
        "ЮП-БЕЗ-НОРМ",
        "ЮП-ФЛАГ",
        "ЮП-ПАРТНЁР",
    }

    single = fields["ЮП-ОДИН"]
    assert single["name"] == "Перила 2780"
    assert single["perimeter_mm"] == pytest.approx(64.2)
    assert single["mount_width_mm"] == pytest.approx(19.35)
    assert single["lengths_mm"] == [2780.0]
    assert single["quantities"] == [72]

    # Несколько длин: норма привязана к длине позиционно, а не «по порядку
    # значений» — пропуск читается как None и не подхватывает чужую норму.
    multi = fields["ЮП-МНОГО"]
    assert dict(zip(multi["lengths_mm"], multi["quantities"])) == {
        2500.0: 48,
        2700.0: None,
        3000.0: 48,
    }

    empty = fields["ЮП-БЕЗ-ДАННЫХ"]
    assert "lengths_mm" not in empty and "quantities" not in empty

    flagged = fields["ЮП-ФЛАГ"]
    assert flagged["skip_shot_blast"] is True
    assert "is_laminated" not in flagged
    assert flagged["notes"] == "прим"
    assert set(flagged["aliases"]) == {"ЭВ-1", "ЭВ-2"}
    assert flagged["pair_partners"] == ["ЮП-ПАРТНЁР"]
    assert fields["ЮП-ПАРТНЁР"]["pair_partners"] == ["ЮП-ФЛАГ"]


async def test_export_excel_preview_is_idempotent(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed_export_catalog(session)
    resp, _ = await _export(client)

    preview = await _upload(client, PREVIEW_URL, resp.content, filename="final_catalog.xlsx")

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["errors"] == []
    assert body["stats"] == {"total": 7, "create": 0, "update": 0, "skip": 7, "errors": 0}
    assert {item["action"] for item in body["items"]} == {"skip"}
