"""Группа эквивалентных артикулов — транзитивное замыкание ``Product.aliases``.

Спека: ``docs/equivalents-pool-spec.md`` §2, ADR-0073. Группа строится на
чтение: узлы — все продукты со ``sku`` (включая неактивные), рёбра —
алиасы в обе стороны, ``group_key = min(product_id)``.
"""

from __future__ import annotations

import pytest
from app.models.product import Product, ProductType
from app.services.product_alias_groups import AliasGroupCache, load_alias_groups
from sqlalchemy import event

pytestmark = pytest.mark.asyncio


def _count_sql(session):
    """Счётчик SQL на время блока — по образцу тестов #290/#292."""
    counter = {"n": 0, "statements": []}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        # SAVEPOINT/RELEASE — служебные операторы тестовой транзакции Cleaner'а.
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1
            counter["statements"].append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _count)


async def _product(
    session,
    sku: str,
    *,
    aliases: list[str] | None = None,
    is_active: bool = True,
) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=is_active,
        aliases=list(aliases or []),
    )
    session.add(product)
    await session.flush()
    return product


async def test_direct_alias_forms_one_group(session) -> None:
    product_a = await _product(session, "ALG-A", aliases=["ALG-B"])
    product_b = await _product(session, "ALG-B")
    await session.commit()

    groups = await load_alias_groups(session, {product_a.id})

    group = groups.group_for(product_a.id)
    assert group is not None
    assert group.product_ids == (product_a.id, product_b.id)
    assert group.skus == ("ALG-A", "ALG-B")
    assert group.key == product_a.id
    # Второй участник тоже виден, хотя его не было в подсказке product_ids.
    assert groups.group_for(product_b.id) is group
    assert groups.group_key(product_b.id) == product_a.id


async def test_alias_declared_on_either_side_is_symmetric(session) -> None:
    """Алиас только у одного из пары связывает обоих: ребро не направленное."""
    product_a = await _product(session, "ALG-SYM-A")
    product_b = await _product(session, "ALG-SYM-B", aliases=["ALG-SYM-A"])
    await session.commit()

    groups = await load_alias_groups(session)

    assert groups.expand([product_a.id]) == {product_a.id, product_b.id}
    assert groups.group_for(product_a.id) is groups.group_for(product_b.id)


async def test_aliases_are_transitive(session) -> None:
    """A~B и B~C — одна группа; A и C напрямую не связаны."""
    product_a = await _product(session, "ALG-T-A", aliases=["ALG-T-B"])
    product_b = await _product(session, "ALG-T-B", aliases=["ALG-T-C"])
    product_c = await _product(session, "ALG-T-C")
    await session.commit()

    groups = await load_alias_groups(session, {product_a.id})

    group = groups.group_for(product_c.id)
    assert group is not None
    assert group.product_ids == (product_a.id, product_b.id, product_c.id)
    assert groups.expand([product_c.id]) == {
        product_a.id,
        product_b.id,
        product_c.id,
    }


async def test_inactive_product_is_a_group_member(session) -> None:
    product_active = await _product(session, "ALG-ACTIVE")
    product_inactive = await _product(
        session,
        "ALG-INACTIVE",
        aliases=["ALG-ACTIVE"],
        is_active=False,
    )
    await session.commit()

    groups = await load_alias_groups(session)

    assert groups.expand([product_active.id]) == {
        product_active.id,
        product_inactive.id,
    }


async def test_alias_to_missing_sku_is_ignored(session) -> None:
    product_a = await _product(session, "ALG-GHOST-A", aliases=["ALG-NOT-EXISTS"])
    product_b = await _product(session, "ALG-GHOST-B")
    await session.commit()

    groups = await load_alias_groups(session)

    group = groups.group_for(product_a.id)
    assert group is not None
    assert group.product_ids == (product_a.id,)
    assert groups.group_for(product_b.id) is not group


async def test_alias_matching_normalizes_sku(session) -> None:
    """Регистр, пробелы и варианты тире — тот же артикул (``normalize_sku``)."""
    product_a = await _product(session, "ALG-NORM-1")
    product_b = await _product(
        session,
        "ALG-NORM-2",
        aliases=["  alg\u2013norm\u20131 "],
    )
    await session.commit()

    groups = await load_alias_groups(session)

    assert groups.expand([product_b.id]) == {product_a.id, product_b.id}


async def test_normalization_collision_resolves_to_min_product_id(session) -> None:
    """Два продукта с одинаковым нормализованным SKU детерминированно слиты.

    Одинаковый нормализованный артикул — тот же физический артикул, поэтому
    узлы объединяются, а alias-ссылка попадает в группу с минимальным id.
    """
    product_first = await _product(session, "ALG-COL-1")
    product_second = await _product(session, "alg-col-1")
    product_other = await _product(
        session,
        "ALG-COL-OTHER",
        aliases=["ALG-COL-1"],
    )
    await session.commit()

    groups = await load_alias_groups(session, {product_other.id})

    group = groups.group_for(product_other.id)
    assert group is not None
    assert group.product_ids == (
        product_first.id,
        product_second.id,
        product_other.id,
    )
    assert group.key == product_first.id


async def test_cache_spends_exactly_one_select(session) -> None:
    """Повторный вызов с тем же кэшем не даёт SQL: справочник прочитан один раз."""
    product_a = await _product(session, "ALG-CACHE-A", aliases=["ALG-CACHE-B"])
    product_b = await _product(session, "ALG-CACHE-B")
    await session.commit()

    cache = AliasGroupCache()
    counter, remove = _count_sql(session)
    try:
        first = await load_alias_groups(session, {product_a.id}, cache=cache)
        second = await load_alias_groups(session, {product_b.id}, cache=cache)
    finally:
        remove()

    assert counter["n"] == 1, counter["statements"]
    assert first is second
    assert second.expand([product_b.id]) == {product_a.id, product_b.id}


async def test_without_cache_every_call_reads_catalog(session) -> None:
    product = await _product(session, "ALG-NOCACHE")
    await session.commit()

    counter, remove = _count_sql(session)
    try:
        await load_alias_groups(session, {product.id})
        await load_alias_groups(session, {product.id})
    finally:
        remove()

    assert counter["n"] == 2, counter["statements"]
