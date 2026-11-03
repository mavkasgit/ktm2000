"""Экран остатков: строка ответа — группа эквивалентов (спека §7–§8, ADR-0073).

``GET /api/stock/balance`` группирует строки ``StockBalance`` по
``(alias_group_key, участок, качество, размер, пройденные операции)``:
склад, где A и B — один профиль, показывает одну кучу. Пагинация, сортировка
и ``total`` считаются по группам: иначе группа разъедется по страницам и
сумма «одной кучи» станет ложной.

``GET /api/stock/balance/by-product/{id}`` остаётся SKU-уровнем — это
детализация одного артикула, группы ей не нужны.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.security import create_access_token
from app.models import Product, ProductType, Section, User, UserRole
from app.models.route import SectionOperation
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

DIMS_27 = {"length_mm": 2700}


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username="alias-bal-tester",
        email="alias-bal-tester@local",
        full_name="Alias Balance Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth(client: AsyncClient, user: User) -> None:
    client.headers["Authorization"] = f"Bearer {create_access_token(subject=user.email)}"


async def _make_product(
    session: AsyncSession,
    sku: str,
    *,
    aliases: list[str] | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        aliases=list(aliases or []),
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, *, code: str, name: str | None = None) -> Section:
    section = Section(
        code=code,
        name=name or code,
        type="raw_stock",
        is_active=True,
        sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _make_operation(
    session: AsyncSession, *, code: str, name: str, sort_order: int,
) -> Section:
    """Участок справочника с одной значимой производственной операцией."""
    section = Section(
        code=f"OPS-{code}",
        name=name,
        type="production",
        is_active=True,
        sort_order=sort_order,
    )
    session.add(section)
    await session.flush()
    session.add(
        SectionOperation(
            section_id=section.id,
            operation_code=code,
            operation_name=name,
            operation_type="production",
            is_significant=True,
            sort_order=sort_order,
        )
    )
    await session.flush()
    return section


async def _seed(
    session: AsyncSession,
    *,
    product: Product,
    location: Section,
    quantity: Decimal | float,
    user_id: int,
    quantity_state: QualityState = QualityState.GOOD,
    dimensions: dict | None = None,
    operations: list[str] | None = None,
) -> None:
    """Приход остатка через ledger: ключ строки канонизируется сервисом."""
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=location.id,
            quantity=Decimal(str(quantity)),
            reason=Reason.MANUAL_IN,
            quality_state=quantity_state,
            dimensions=dimensions,
            completed_operations=operations,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _list_balances(client: AsyncClient, **params) -> dict:
    resp = await client.get("/api/stock/balance", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_equivalent_articles_on_same_axes_are_one_row(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """A и B одной группы, тот же участок/качество/размер/операции — одна строка."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-SAME-LOC")
    product_a = await _make_product(session, sku="ALIAS-SAME-A", aliases=["ALIAS-SAME-B"])
    product_b = await _make_product(session, sku="ALIAS-SAME-B")

    await _seed(session, product=product_a, location=location, quantity=10, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=5, user_id=user.id)

    body = await _list_balances(client, location_id=location.id)
    assert body["total"] == 1, body
    assert len(body["balances"]) == 1
    row = body["balances"][0]

    # Сумма кучи и обратная совместимость полей строки.
    assert row["balance_qty"] == "15.000"
    assert row["quality_state"] == "good"
    assert row["location_id"] == location.id
    assert row["dimensions"] is None
    assert row["completed_operations"] is None

    # Группа: ключ — минимальный product_id, подпись — SKU по возрастанию id.
    assert row["alias_group_key"] == min(product_a.id, product_b.id)
    assert row["alias_group_skus"] == ["ALIAS-SAME-A", "ALIAS-SAME-B"]
    assert row["product_id"] == min(product_a.id, product_b.id)
    assert row["product_sku"] == "ALIAS-SAME-A"

    # Раскрытие — фактические SKU-строки с их balance_id и количеством.
    assert [
        (item["product_id"], item["sku"], item["quantity"])
        for item in row["items"]
    ] == [
        (product_a.id, "ALIAS-SAME-A", "10.000"),
        (product_b.id, "ALIAS-SAME-B", "5.000"),
    ]
    assert row["id"] == min(item["balance_id"] for item in row["items"])


async def test_group_does_not_merge_across_axes(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Участок, качество, размер и операции — часть ключа группы.

    ``None`` и ``[]`` операций — разные группы (ADR-0055), как и разные размеры.
    """
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-AXES-LOC")
    product_a = await _make_product(session, sku="ALIAS-AXES-A", aliases=["ALIAS-AXES-B"])
    product_b = await _make_product(session, sku="ALIAS-AXES-B")

    await _seed(
        session, product=product_a, location=location, quantity=10, user_id=user.id,
        operations=None,
    )
    await _seed(
        session, product=product_b, location=location, quantity=5, user_id=user.id,
        operations=[],
    )
    await _seed(
        session, product=product_a, location=location, quantity=3, user_id=user.id,
        dimensions=DIMS_27, operations=None,
    )
    await _seed(
        session, product=product_b, location=location, quantity=2, user_id=user.id,
        quantity_state=QualityState.SCRAP, operations=[],
    )

    body = await _list_balances(client, location_id=location.id)
    rows = body["balances"]
    assert body["total"] == 4
    assert len(rows) == 4
    # Ни одна группа не сложила чужие оси в сумму.
    assert sorted(Decimal(row["balance_qty"]) for row in rows) == [
        Decimal(2), Decimal(3), Decimal(5), Decimal(10),
    ]
    # Ключ группы у всех строк один, а подпись — все SKU пары.
    assert {row["alias_group_key"] for row in rows} == {min(product_a.id, product_b.id)}
    assert all(row["alias_group_skus"] == ["ALIAS-AXES-A", "ALIAS-AXES-B"] for row in rows)
    # Раскрытие — только фактическая строка этой кучи.
    assert all(len(row["items"]) == 1 for row in rows)


async def test_same_pair_on_two_locations_is_two_piles(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Склад — часть ключа: одна и та же пара на двух участках — две кучи."""
    user = await _make_user(session)
    _auth(client, user)
    loc_a = await _make_location(session, code="ALIAS-TWO-LOC-A")
    loc_b = await _make_location(session, code="ALIAS-TWO-LOC-B")
    product_a = await _make_product(session, sku="ALIAS-TWO-A", aliases=["ALIAS-TWO-B"])
    product_b = await _make_product(session, sku="ALIAS-TWO-B")

    for location, qty_a, qty_b in ((loc_a, 10, 5), (loc_b, 7, 2)):
        await _seed(session, product=product_a, location=location, quantity=qty_a, user_id=user.id)
        await _seed(session, product=product_b, location=location, quantity=qty_b, user_id=user.id)

    body = await _list_balances(client, location_ids=[loc_a.id, loc_b.id])
    rows = body["balances"]
    assert body["total"] == 2
    by_location = {row["location_id"]: row for row in rows}
    assert Decimal(by_location[loc_a.id]["balance_qty"]) == Decimal(15)
    assert Decimal(by_location[loc_b.id]["balance_qty"]) == Decimal(9)
    assert all(len(row["items"]) == 2 for row in rows)


async def test_member_operations_are_canonicalized_into_one_pile(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Порядок кодов в ``completed_operations`` не делит одну кучу на две."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-OPS-LOC")
    product_a = await _make_product(session, sku="ALIAS-OPS-A", aliases=["ALIAS-OPS-B"])
    product_b = await _make_product(session, sku="ALIAS-OPS-B")
    await _make_operation(session, code="OP_A", name="Первая", sort_order=10)
    await _make_operation(session, code="OP_B", name="Вторая", sort_order=20)

    await _seed(
        session, product=product_a, location=location, quantity=4, user_id=user.id,
        operations=["OP_B", "OP_A"],
    )
    await _seed(
        session, product=product_b, location=location, quantity=6, user_id=user.id,
        operations=["OP_A", "OP_B"],
    )

    body = await _list_balances(client, location_id=location.id)
    assert body["total"] == 1
    row = body["balances"][0]
    assert Decimal(row["balance_qty"]) == Decimal(10)
    assert row["completed_operations"] == ["OP_A", "OP_B"]
    assert len(row["items"]) == 2


async def test_filter_by_member_sku_shows_whole_group(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Фильтр по SKU одного члена показывает группу целиком — сумму и все items."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-FILTER-SKU")
    product_a = await _make_product(session, sku="ALIAS-FILTER-A", aliases=["ALIAS-FILTER-B"])
    product_b = await _make_product(session, sku="ALIAS-FILTER-B")
    await _seed(session, product=product_a, location=location, quantity=10, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=5, user_id=user.id)

    body = await _list_balances(client, location_id=location.id, sku="ALIAS-FILTER-B")
    assert body["total"] == 1
    row = body["balances"][0]
    assert Decimal(row["balance_qty"]) == Decimal(15)
    assert [item["sku"] for item in row["items"]] == ["ALIAS-FILTER-A", "ALIAS-FILTER-B"]


async def test_filter_by_member_product_id_shows_group_sum(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Фильтр ``product_id`` — тоже уровень группы, а не строки."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-FILTER-PID")
    product_a = await _make_product(session, sku="ALIAS-FILTER-PID-A", aliases=["ALIAS-FILTER-PID-B"])
    product_b = await _make_product(session, sku="ALIAS-FILTER-PID-B")
    await _seed(session, product=product_a, location=location, quantity=8, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=2, user_id=user.id)

    body = await _list_balances(client, product_id=product_b.id)
    assert body["total"] == 1
    assert Decimal(body["balances"][0]["balance_qty"]) == Decimal(10)
    assert len(body["balances"][0]["items"]) == 2


async def test_filter_by_quantity_matches_group_sum(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Фильтр «Количество» сверяется с видимой суммой группы, а не со строкой.

    Раньше совпадение искалось в ``balance_qty`` каждого члена: запрос
    ``?quantity=111`` возвращал группу, в колонке которой стоит 116. Колонка
    и фильтр обязаны говорить об одном числе.
    """
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-FILTER-QTY")
    product_a = await _make_product(session, sku="ALIAS-FILTER-QTY-A", aliases=["ALIAS-FILTER-QTY-B"])
    product_b = await _make_product(session, sku="ALIAS-FILTER-QTY-B")
    await _seed(session, product=product_a, location=location, quantity=111, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=5, user_id=user.id)

    by_total = await _list_balances(client, location_id=location.id, quantity="116")
    assert by_total["total"] == 1
    assert Decimal(by_total["balances"][0]["balance_qty"]) == Decimal(116)

    by_member = await _list_balances(client, location_id=location.id, quantity="111")
    assert by_member["total"] == 0


async def test_pagination_and_total_are_by_group(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """``total`` и страницы считают группы: группа не разъезжается по страницам."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-PAGE-LOC")

    pairs = []
    for index in (1, 2, 3):
        product_a = await _make_product(
            session,
            sku=f"ALIAS-PAGE-{index}-A",
            aliases=[f"ALIAS-PAGE-{index}-B"],
        )
        product_b = await _make_product(session, sku=f"ALIAS-PAGE-{index}-B")
        pairs.append((product_a, product_b))
        await _seed(session, product=product_a, location=location, quantity=1, user_id=user.id)
        await _seed(session, product=product_b, location=location, quantity=1, user_id=user.id)

    solo = await _make_product(session, sku="ALIAS-PAGE-SOLO")
    await _seed(session, product=solo, location=location, quantity=1, user_id=user.id)

    first = await _list_balances(client, location_id=location.id, limit=2, offset=0)
    second = await _list_balances(client, location_id=location.id, limit=2, offset=2)
    assert first["total"] == 4
    assert second["total"] == 4
    assert len(first["balances"]) == 2
    assert len(second["balances"]) == 2

    first_ids = {row["id"] for row in first["balances"]}
    second_ids = {row["id"] for row in second["balances"]}
    assert first_ids.isdisjoint(second_ids)
    assert len(first_ids | second_ids) == 4

    # 7 строк баланса упакованы в 4 группы: страница из двух групп несёт
    # больше строк, чем limit, но ни одна пара не разрезана.
    assert sum(len(row["items"]) for row in first["balances"]) == 4
    assert [len(row["items"]) for row in [*first["balances"], *second["balances"]]] == [2, 2, 2, 1]


async def test_sort_quantity_uses_group_sum(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Сортировка «Количество» — по сумме группы, а не по строкам."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-SORT-QTY")
    product_a = await _make_product(session, sku="ALIAS-SORT-QTY-A", aliases=["ALIAS-SORT-QTY-B"])
    product_b = await _make_product(session, sku="ALIAS-SORT-QTY-B")
    solo = await _make_product(session, sku="ALIAS-SORT-QTY-SOLO")
    await _seed(session, product=product_a, location=location, quantity=100, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=1, user_id=user.id)
    await _seed(session, product=solo, location=location, quantity=50, user_id=user.id)

    body = await _list_balances(
        client, location_id=location.id, sort="quantity:desc",
    )
    assert [row["balance_qty"] for row in body["balances"]] == ["101.000", "50.000"]


async def test_sort_sku_uses_group_label(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Сортировка «Артикул» — по подписи группы, детерминированно."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-SORT-SKU")
    product_a = await _make_product(session, sku="ALIAS-ZZ-A", aliases=["ALIAS-ZZ-B"])
    product_b = await _make_product(session, sku="ALIAS-ZZ-B")
    solo = await _make_product(session, sku="ALIAS-MM-SOLO")
    await _seed(session, product=product_a, location=location, quantity=1, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=1, user_id=user.id)
    await _seed(session, product=solo, location=location, quantity=1, user_id=user.id)

    ascending = await _list_balances(client, location_id=location.id, sort="sku:asc")
    descending = await _list_balances(client, location_id=location.id, sort="sku:desc")
    assert [row["product_sku"] for row in ascending["balances"]] == [
        "ALIAS-MM-SOLO", "ALIAS-ZZ-A",
    ]
    assert [row["product_sku"] for row in descending["balances"]] == [
        "ALIAS-ZZ-A", "ALIAS-MM-SOLO",
    ]


async def test_empty_sku_label_goes_last_in_both_directions(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Пустая подпись группы уходит в конец и при ``asc``, и при ``desc``."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-SORT-NULL")
    named = await _make_product(session, sku="ALIAS-NAMED")
    nameless = await _make_product(session, sku="")
    await _seed(session, product=named, location=location, quantity=1, user_id=user.id)
    await _seed(session, product=nameless, location=location, quantity=1, user_id=user.id)

    for order in ("asc", "desc"):
        body = await _list_balances(
            client, location_id=location.id, sort=f"sku:{order}",
        )
        assert body["balances"][-1]["alias_group_skus"] == [], (order, body["balances"])


async def test_by_product_stays_sku_level(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Детализация по продукту не группируется: это SKU-уровень."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-BYPROD-LOC")
    product_a = await _make_product(session, sku="ALIAS-BYPROD-A", aliases=["ALIAS-BYPROD-B"])
    product_b = await _make_product(session, sku="ALIAS-BYPROD-B")
    await _seed(session, product=product_a, location=location, quantity=10, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=5, user_id=user.id)

    resp = await client.get(f"/api/stock/balance/by-product/{product_a.id}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["product_id"] == product_a.id
    assert rows[0]["balance_qty"] == "10.000"
    assert "alias_group_key" not in rows[0]
    assert "items" not in rows[0]


async def test_alias_groups_read_does_not_grow_with_rows(
    client: AsyncClient, session: AsyncSession,
) -> None:
    """Справочник групп читается один раз на запрос — без N+1 по строкам."""
    user = await _make_user(session)
    _auth(client, user)
    location = await _make_location(session, code="ALIAS-SQL-LOC")
    product_a = await _make_product(session, sku="ALIAS-SQL-A", aliases=["ALIAS-SQL-B"])
    product_b = await _make_product(session, sku="ALIAS-SQL-B")
    await _seed(session, product=product_a, location=location, quantity=1, user_id=user.id)
    await _seed(session, product=product_b, location=location, quantity=1, user_id=user.id)

    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        first = await _list_balances(client, location_id=location.id)
        first_count = counter["n"]
        # Больше строк и групп того же участка: число SQL не должно вырасти.
        # Сид сам ходит в базу, поэтому счётчик сбрасывается ПОСЛЕ него.
        for index in range(5):
            extra = await _make_product(session, sku=f"ALIAS-SQL-EXTRA-{index}")
            await _seed(session, product=extra, location=location, quantity=1, user_id=user.id)
        counter["n"] = 0
        second = await _list_balances(client, location_id=location.id)
        second_count = counter["n"]
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert second["total"] == first["total"] + 5
    assert second_count == first_count, (first_count, second_count)
