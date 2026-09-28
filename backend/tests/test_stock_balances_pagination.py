"""Pagination, total and search for GET /api/stock/balance."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Product, ProductType, Section, User, UserRole
from app.stock import QualityState, Reason, StockCommand, StockCommandService


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="bal-page-tester",
        email="bal-page-tester@local",
        full_name="Bal Page Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


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


async def _make_location(session: AsyncSession, *, code: str, name: str) -> Section:
    section = Section(
        code=code,
        name=name,
        type="raw_stock",
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _seed_balances(
    session: AsyncSession,
    *,
    location_id: int,
    user_id: int,
    count: int,
    sku_prefix: str = "BAL-PAGE",
) -> list[Product]:
    svc = StockCommandService()
    products: list[Product] = []
    for i in range(count):
        product = await _make_product(session, sku=f"{sku_prefix}-{i:03d}")
        products.append(product)
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=user_id,
        ))
    await session.commit()
    return products


@pytest.mark.asyncio
async def test_balances_default_limit_returns_total(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-1", name="Balance Alpha")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=65,
    )

    resp = await client.get(f"/api/stock/balance?location_id={location.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["balances"]) == 50
    assert body["total"] == 65
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_balances_offset_pagination(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-2", name="Balance Beta")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=75,
    )

    first = await client.get(
        f"/api/stock/balance?location_id={location.id}&limit=50&offset=0",
    )
    second = await client.get(
        f"/api/stock/balance?location_id={location.id}&limit=50&offset=50",
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_ids = {row["id"] for row in first.json()["balances"]}
    second_ids = {row["id"] for row in second.json()["balances"]}
    assert len(first_ids) == 50
    assert len(second_ids) == 25
    assert first_ids.isdisjoint(second_ids)
    assert first.json()["total"] == 75
    assert second.json()["total"] == 75


@pytest.mark.asyncio
async def test_balances_search_finds_record_on_second_page(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LOC-3", name="Balance Gamma")
    await _seed_balances(
        session,
        location_id=location.id,
        user_id=user.id,
        count=60,
        sku_prefix="ORDINARY",
    )
    marker_product = await _make_product(session, sku="UNIQUE-BAL-MARKER-42")
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=marker_product.id,
        to_location_id=location.id,
        quantity=Decimal("5"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&search=UNIQUE-BAL-MARKER-42&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["balances"]) == 1
    assert body["balances"][0]["product_sku"] == "UNIQUE-BAL-MARKER-42"


@pytest.mark.asyncio
async def test_balances_limit_max_validation(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.get("/api/stock/balance?limit=1000")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_balances_sort_by_quantity(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-SORT-LOC", name="Sort Balance")
    product_low = await _make_product(session, sku="BAL-SORT-LOW")
    product_high = await _make_product(session, sku="BAL-SORT-HIGH")
    product_mid = await _make_product(session, sku="BAL-SORT-MID")
    svc = StockCommandService()
    for product, qty in (
        (product_low, Decimal("3")),
        (product_high, Decimal("30")),
        (product_mid, Decimal("7")),
    ):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&sort=quantity:asc&limit=50",
    )
    assert resp.status_code == 200, resp.text
    quantities = [Decimal(row["balance_qty"]) for row in resp.json()["balances"]]
    assert quantities == sorted(quantities)


@pytest.mark.asyncio
async def test_balances_filter_quality_state(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    product = await _make_product(session, sku="BAL-FILTER-QS")
    location = await _make_location(session, code="BAL-FILTER-LOC", name="Filter Balance")
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("10"),
        reason=Reason.MANUAL_IN,
        quality_state=QualityState.GOOD,
        created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=location.id,
        quantity=Decimal("4"),
        reason=Reason.MANUAL_IN,
        quality_state=QualityState.SCRAP,
        created_by=user.id,
    ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&quality_state=scrap&limit=50&offset=0",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["balances"]) == 1
    assert body["balances"][0]["quality_state"] == "scrap"


@pytest.mark.asyncio
async def test_balances_location_ids_filter(client, session: AsyncSession):
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    loc_a = await _make_location(session, code="BAL-MULTI-A", name="Multi A")
    loc_b = await _make_location(session, code="BAL-MULTI-B", name="Multi B")
    loc_c = await _make_location(session, code="BAL-MULTI-C", name="Multi C")
    product_a = await _make_product(session, sku="BAL-MULTI-A-SKU")
    product_b = await _make_product(session, sku="BAL-MULTI-B-SKU")
    product_c = await _make_product(session, sku="BAL-MULTI-C-SKU")
    svc = StockCommandService()
    for product, location in (
        (product_a, loc_a),
        (product_b, loc_b),
        (product_c, loc_c),
    ):
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_ids={loc_a.id}&location_ids={loc_b.id}&limit=50",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    location_ids = {row["location_id"] for row in body["balances"]}
    assert location_ids == {loc_a.id, loc_b.id}


@pytest.mark.asyncio
async def test_balances_multi_sort_quantity_then_sku(client, session: AsyncSession):
    """Вторая колонка ?sort= перебивает tiebreaker первой (порядок создания)."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-MSORT-LOC", name="Multi Sort Balance")
    svc = StockCommandService()
    # Артикулы заводятся по возрастанию: порядок создания (product_id) совпадает
    # с sku:asc и противоположен sku:desc — без этого вторая колонка ничего бы
    # не поменяла и тест прошёл бы на одноприоритетной сортировке.
    for sku in ("BAL-MS-A", "BAL-MS-B", "BAL-MS-C"):
        product = await _make_product(session, sku=sku)
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("7"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    single = await client.get(
        f"/api/stock/balance?location_id={location.id}&sort=quantity:asc&limit=50",
    )
    multi = await client.get(
        f"/api/stock/balance?location_id={location.id}&sort=quantity:asc,sku:desc&limit=50",
    )
    assert single.status_code == 200, single.text
    assert multi.status_code == 200, multi.text

    single_skus = [row["product_sku"] for row in single.json()["balances"]]
    multi_skus = [row["product_sku"] for row in multi.json()["balances"]]
    assert single_skus == ["BAL-MS-A", "BAL-MS-B", "BAL-MS-C"]
    assert multi_skus == ["BAL-MS-C", "BAL-MS-B", "BAL-MS-A"]
    assert single_skus != multi_skus


@pytest.mark.asyncio
async def test_balances_grouping_levels_kept_on_ties(client, session: AsyncSession):
    """При равных количествах строки одного товара идут подряд и по своим локациям."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    loc_a = await _make_location(session, code="BAL-GRP-A", name="Group A")
    loc_b = await _make_location(session, code="BAL-GRP-B", name="Group B")
    svc = StockCommandService()
    # Порядок проводок внутри товара НАМЕРЕННО обратный порядку локаций:
    # так тест краснеет, если из ORDER BY выпал уровень «location_id».
    for sku, locations in (
        ("BAL-GRP-1", (loc_b, loc_a)),
        ("BAL-GRP-2", (loc_a, loc_b)),
    ):
        product = await _make_product(session, sku=sku)
        for location in locations:
            await svc.record(session, StockCommand(
                product_id=product.id,
                to_location_id=location.id,
                quantity=Decimal("4"),
                reason=Reason.MANUAL_IN,
                created_by=user.id,
            ))
    await session.commit()

    resp = await client.get(
        f"/api/stock/balance?location_ids={loc_a.id}&location_ids={loc_b.id}"
        f"&sort=quantity:asc&limit=50",
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["balances"]
    assert len(rows) == 4
    assert {Decimal(row["balance_qty"]) for row in rows} == {Decimal("4")}

    assert [(row["product_sku"], row["location_id"]) for row in rows] == [
        ("BAL-GRP-1", loc_a.id),
        ("BAL-GRP-1", loc_b.id),
        ("BAL-GRP-2", loc_a.id),
        ("BAL-GRP-2", loc_b.id),
    ]


@pytest.mark.asyncio
async def test_balances_default_order_is_sku_asc(client, session: AsyncSession):
    """Без параметра сортировки порядок прежний: артикул по возрастанию."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-DEF-LOC", name="Default Order Balance")
    svc = StockCommandService()
    # Создаём НЕ по алфавиту: сортировка по product_id дала бы другой порядок.
    for sku in ("BAL-DEF-C", "BAL-DEF-A", "BAL-DEF-B"):
        product = await _make_product(session, sku=sku)
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal("1"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    resp = await client.get(f"/api/stock/balance?location_id={location.id}&limit=50")
    assert resp.status_code == 200, resp.text
    assert [row["product_sku"] for row in resp.json()["balances"]] == [
        "BAL-DEF-A",
        "BAL-DEF-B",
        "BAL-DEF-C",
    ]


@pytest.mark.asyncio
async def test_balances_rejects_unknown_sort_field(client, session: AsyncSession):
    """Кликнул неизвестную колонку — 400, а не молчаливый откат на дефолт."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.get("/api/stock/balance?sort=unknown:asc")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_balances_rejects_unknown_direction(client, session: AsyncSession):
    """Направление вне asc/desc — 400, а не asc по умолчанию."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.get("/api/stock/balance?sort=quantity:sideways")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_balances_ignores_legacy_sort_by_params(client, session: AsyncSession):
    """Сепарактные sort_by/sort_order больше не объявлены и не сортируют."""
    user = await _make_user(session)
    token = create_access_token(subject=user.email)
    client.headers["Authorization"] = f"Bearer {token}"

    location = await _make_location(session, code="BAL-LEG-LOC", name="Legacy Params Balance")
    svc = StockCommandService()
    for sku, qty in (("BAL-LEG-A", "1"), ("BAL-LEG-B", "3"), ("BAL-LEG-C", "2")):
        product = await _make_product(session, sku=sku)
        await svc.record(session, StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal(qty),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
    await session.commit()

    legacy = await client.get(
        f"/api/stock/balance?location_id={location.id}"
        f"&sort_by=quantity&sort_order=desc&limit=50",
    )
    assert legacy.status_code == 200, legacy.text
    assert [row["product_sku"] for row in legacy.json()["balances"]] == [
        "BAL-LEG-A",
        "BAL-LEG-B",
        "BAL-LEG-C",
    ]

    # Данные подобраны так, что «по количеству убыванию» — другой порядок:
    # значит тест краснеет, если legacy-параметры вдруг начнут влиять.
    by_quantity = await client.get(
        f"/api/stock/balance?location_id={location.id}&sort=quantity:desc&limit=50",
    )
    assert by_quantity.status_code == 200, by_quantity.text
    quantity_skus = [row["product_sku"] for row in by_quantity.json()["balances"]]
    assert quantity_skus == ["BAL-LEG-B", "BAL-LEG-C", "BAL-LEG-A"]