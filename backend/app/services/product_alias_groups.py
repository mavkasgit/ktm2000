"""Группа эквивалентных артикулов — транзитивное замыкание ``Product.aliases``.

Спека: ``docs/equivalents-pool-spec.md`` §2, ADR-0073. Группа строится на
чтение и не хранится: узлы — все продукты со ``sku`` (включая неактивные),
рёбра — ``Product.aliases`` в обе стороны. Alias-SKU без строки продукта
игнорируется: остатка у него быть не может.

Модуль — единственный владелец замыкания: импорт, выдача и индикатор берут
группы здесь, а не строят их сами. ``AliasGroupCache`` живёт на время одного
HTTP-запроса (по образцу ``PairResolutionCache``): справочник читается один
раз, повторные вызовы не дают SQL.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.import_normalization import normalize_sku


@dataclass(frozen=True)
class AliasGroup:
    """Одна группа эквивалентов.

    ``key`` — минимальный ``product_id`` группы (канонического артикула нет);
    ``product_ids`` и ``skus`` — по возрастанию ``id``, в одном порядке.
    """

    key: int
    product_ids: tuple[int, ...]
    skus: tuple[str, ...]


@dataclass(frozen=True)
class AliasGroups:
    """Индекс групп: продукт → его группа."""

    groups: tuple[AliasGroup, ...]
    _by_product: dict[int, AliasGroup] = field(
        init=False, repr=False, compare=False
    )
    _by_key: dict[int, AliasGroup] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_product: dict[int, AliasGroup] = {}
        by_key: dict[int, AliasGroup] = {}
        for group in self.groups:
            by_key[group.key] = group
            for product_id in group.product_ids:
                by_product[product_id] = group
        object.__setattr__(self, "_by_product", by_product)
        object.__setattr__(self, "_by_key", by_key)

    def group_for(self, product_id: int) -> AliasGroup | None:
        """Группа продукта; ``None`` — продукт не попал в загрузку."""
        return self._by_product.get(int(product_id))

    def group_key(self, product_id: int) -> int | None:
        """``group_key`` продукта; ``None`` — продукт не попал в загрузку."""
        group = self.group_for(product_id)
        return group.key if group is not None else None

    def group_by_key(self, key: int) -> AliasGroup | None:
        """Группа по её ``group_key``."""
        return self._by_key.get(int(key))

    def expand(self, product_ids: Iterable[int]) -> set[int]:
        """Все продукты групп, в которые входят ``product_ids``.

        Неразрешённые продукты остаются в результате сами собой: вызывающий
        получает надмножество переданных id, а не теряет их.
        """
        expanded = {int(product_id) for product_id in product_ids}
        for product_id in tuple(expanded):
            group = self._by_product.get(product_id)
            if group is not None:
                expanded.update(group.product_ids)
        return expanded


class AliasGroupCache:
    """Кэш групп на один HTTP-запрос: один SELECT справочника.

    Создаёт его обработчик и передаёт в :func:`load_alias_groups`. Первый
    вызов читает ``Product.id, Product.sku, Product.aliases`` по всему
    справочнику, дальше union-find уже в памяти — повторный вызов SQL не даёт.
    """

    __slots__ = ("_groups",)

    def __init__(self) -> None:
        self._groups: AliasGroups | None = None

    @property
    def is_loaded(self) -> bool:
        return self._groups is not None

    async def load(self, db: AsyncSession) -> AliasGroups:
        if self._groups is None:
            self._groups = await _load_alias_groups(db)
        return self._groups


async def load_alias_groups(
    db: AsyncSession,
    product_ids: Iterable[int] | None = None,
    *,
    cache: AliasGroupCache | None = None,
) -> AliasGroups:
    """Загрузить группы эквивалентов.

    ``product_ids`` — подсказка вызывающего (какие артикулы интересуют), но
    замыкание требует весь справочник: группа продукта неполна без её
    остальных членов. Поэтому читается весь каталог, а индекс отвечает
    ``group_for`` и для продуктов вне подсказки.

    ``cache`` — кэш одного HTTP-запроса; с ним ровно один SELECT на жизнь
    кэша. Без кэша — один SELECT на вызов.
    """
    # Подсказка не сужает загрузку: см. docstring выше.
    if cache is not None:
        return await cache.load(db)
    return await _load_alias_groups(db)


async def _load_alias_groups(db: AsyncSession) -> AliasGroups:
    """Прочитать справочник и собрать группы union-find в памяти."""
    rows = (
        await db.execute(
            select(Product.id, Product.sku, Product.aliases).where(
                Product.sku.isnot(None)
            )
        )
    ).all()

    # Узел — только продукт с непустым SKU: безымянный артикул нельзя
    # сопоставить ни с одним alias-текстом.
    products: list[tuple[int, str, tuple[str, ...]]] = []
    for product_id, sku, aliases in rows:
        if not normalize_sku(sku or ""):
            continue
        products.append(
            (
                int(product_id),
                str(sku),
                tuple(str(alias) for alias in (aliases or ())),
            )
        )
    if not products:
        return AliasGroups(())

    parent: dict[int, int] = {product_id: product_id for product_id, _sku, _ in products}

    def find(product_id: int) -> int:
        root = product_id
        while parent[root] != root:
            root = parent[root]
        while parent[product_id] != root:
            parent[product_id], product_id = root, parent[product_id]
        return root

    def union(left: int, right: int) -> None:
        # Корень — минимальный id: group_key = min(product_id) получается сам.
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        parent[high] = low

    # Нормализованный SKU → минимальный product_id. Коллизия нормализации
    # (две строки дают один normalize_sku) — один и тот же физический
    # артикул: узлы сливаются, alias-ссылка попадает в минимальный id.
    id_by_normalized_sku: dict[str, int] = {}
    for product_id, sku, _aliases in products:
        normalized = normalize_sku(sku)
        existing = id_by_normalized_sku.get(normalized)
        if existing is None:
            id_by_normalized_sku[normalized] = product_id
            continue
        id_by_normalized_sku[normalized] = min(existing, product_id)
        union(existing, product_id)

    # Ребро объявлено в одну сторону, но связывает обоих: union не направлен.
    # Alias на несуществующий SKU в индексе отсутствует и просто игнорируется.
    for product_id, _sku, aliases in products:
        for alias in aliases:
            target_id = id_by_normalized_sku.get(normalize_sku(alias))
            if target_id is not None:
                union(product_id, target_id)

    members_by_root: dict[int, list[tuple[int, str]]] = {}
    for product_id, sku, _aliases in products:
        members_by_root.setdefault(find(product_id), []).append((product_id, sku))

    groups: list[AliasGroup] = []
    for root in sorted(members_by_root):
        members = sorted(members_by_root[root], key=lambda item: item[0])
        groups.append(
            AliasGroup(
                key=root,
                product_ids=tuple(product_id for product_id, _sku in members),
                skus=tuple(sku for _product_id, sku in members),
            )
        )
    return AliasGroups(tuple(groups))
