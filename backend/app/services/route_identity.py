"""Поиск маршрута по идентичности — единственное место, где он задан (#230).

ADR-0051 объявил идентичность маршрута единой: код идентифицирует, имя —
подпись. Пока это правило жило в вызывающих, оно разошлось на семь
запросов, и каждое набирало свой набор условий: ручной путь про код не
знал вовсе, ``route_matcher`` отсекал архивные маршруты, сид — нет. Из
этого разнобоя вырос дефект #228: уборка сирот сносила эталонные
маршруты завода, потому что «нет связей» значило для неё «нет данных».
Перечисление ниже — единственное, где эти условия задаются.

Различия между вызывающими явны параметрами, а не новой копией условий:

* ``code`` — искать по коду (импорт и сид знают код точно) либо по имени;
* ``legacy_name_only`` — по имени искать ТОЛЬКО среди строк ``code IS
  NULL``. Это переходное состояние базы: маршруты, созданные импортом до
  #230, кода не имеют, и иначе стали бы недостижимыми. Найденный по имени
  маршрут с кодом — не наш, опознавать его по подписи нельзя (ADR-0051
  п. 3). Для ручного пути флаг снят: там код не играет роли, и с фильтром
  проверка уникальности имени пропускала бы автомаршрут, превращая понятный
  409 в ``IntegrityError`` по коду;
* ``only_active`` — оставить только активные. Архивный маршрут назначением
  не считается, но сид его обновлять обязан, иначе повторный ``run_seed``
  плодит дубли: поэтому флаг по умолчанию снят, а не включён.

Порядок выборки всегда ``id`` ASC — самый старый. Так поступают сид и
импорт, и это совпадает с тем, кого обновляет ``run_seed``; выбор «самого
свежего» при ``limit(1)`` давал бы разные ответы на одних и тех же данных
и тихо менял бы результат на дублях.

Сверки сигнатуры здесь нет и быть не должно: она требует чтения этапов и
живёт отдельным явным шагом у вызывающего (ADR-0051 п. 4).
"""
from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import ProductionRoute

__all__ = [
    "find_route_by_code",
    "find_route_by_name",
    "route_identity_query",
]


def route_identity_query(
    *,
    code: str | None = None,
    name: str | None = None,
    legacy_name_only: bool = True,
    only_active: bool = False,
    exclude_id: int | None = None,
) -> Select[tuple[ProductionRoute]]:
    """Запрос маршрута по идентичности (ADR-0051).

    Ровно один из ``code``/``name``; ``name`` с ``legacy_name_only`` ищется
    среди строк без кода. ``limit(1)`` обязателен: снятая уникальность
    имени означает, что совпадений может быть сколько угодно, а ``db.scalar``
    на нескольких строках raises.
    """
    if code is not None and name is not None:
        raise ValueError("код и имя одновременно не ищутся: это разные входы")
    if code is None and name is None:
        raise ValueError("нечего искать: нужен либо код, либо имя")

    if code is not None:
        stmt = select(ProductionRoute).where(ProductionRoute.code == code)
    else:
        assert name is not None
        stmt = select(ProductionRoute).where(ProductionRoute.name == name)
        if legacy_name_only:
            stmt = stmt.where(ProductionRoute.code.is_(None))

    if only_active:
        stmt = stmt.where(ProductionRoute.is_active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(ProductionRoute.id != exclude_id)
    return stmt.order_by(ProductionRoute.id).limit(1)


async def find_route_by_code(
    db: AsyncSession,
    code: str,
    *,
    only_active: bool = False,
) -> ProductionRoute | None:
    """Маршрут с таким кодом."""
    return await db.scalar(route_identity_query(code=code, only_active=only_active))


async def find_route_by_name(
    db: AsyncSession,
    name: str,
    *,
    legacy_name_only: bool = True,
    only_active: bool = False,
    exclude_id: int | None = None,
) -> ProductionRoute | None:
    """Маршрут с таким именем; по умолчанию — только среди строк без кода."""
    return await db.scalar(
        route_identity_query(
            name=name,
            legacy_name_only=legacy_name_only,
            only_active=only_active,
            exclude_id=exclude_id,
        )
    )
