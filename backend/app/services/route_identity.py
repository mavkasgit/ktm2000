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

Порядок поиска (сначала код, и лишь затем legacy-имя) объявлен тоже здесь —
в :func:`find_route_by_identity` (#326): это то же понятие тождества, что и
условия запроса, а не отдельная политика вызывающего. Импорт, автоматчик,
сид и батч-снимок зовут её, отличаясь только фильтрами и кэшами.

Сверки сигнатуры здесь нет и быть не должно: она требует чтения этапов и
живёт отдельным явным шагом у вызывающего (ADR-0051 п. 4).
"""
from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import ProductionRoute

__all__ = [
    "MATCH_BY_CODE",
    "MATCH_BY_LEGACY_NAME",
    "RouteIdentityMatch",
    "find_route_by_code",
    "find_route_by_identity",
    "find_route_by_name",
    "route_identity_query",
]

#: Чем маршрут опознан в порядке тождества: по коду (идентичность) либо по
#: legacy-имени (подпись в переходном состоянии базы).
MATCH_BY_CODE = "code"
MATCH_BY_LEGACY_NAME = "legacy_name"


@dataclass(frozen=True, slots=True)
class RouteIdentityMatch:
    """Найденный маршрут и то, чем он опознан.

    ``matched_by`` нужен вызывающим, которые продолжают работу по-разному:
    конфликт сигнатуры — шаг только для кода (ADR-0051 п. 4), а найденное по
    коду и найденное по имени нельзя перепутать местами.
    """

    route: ProductionRoute
    matched_by: str


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


async def find_route_by_identity(
    db: AsyncSession,
    *,
    code: str | None,
    name: str | None,
    only_active: bool = False,
    code_cache: MutableMapping[str, ProductionRoute | None] | None = None,
    name_cache: MutableMapping[str, ProductionRoute | None] | None = None,
) -> RouteIdentityMatch | None:
    """Маршрут по порядку тождества: сначала код, затем legacy-имя (#326).

    Порядок объявлен здесь один раз, и это часть тождества, а не политика
    вызывающего: код идентифицирует маршрут, имя — подпись (ADR-0051).
    Импорт, автоматчик и сид зовут эту функцию, отличаясь только
    ``only_active`` и кэшами; батч-снимок передаёт свои словари, поэтому
    повторяет тот же порядок, не повторяя его код.

    По коду ищется всегда, по имени — только если по коду ничего нет (или
    кода нет вовсе, например у пересборки без этапов). Имя берётся среди
    строк без кода: у маршрута с кодом своя идентичность, и опознавать его
    подписью нельзя (ADR-0051 п. 3).

    ``code_cache``/``name_cache`` — мемоизация вызывающего на батч. Значение
    под ключом, в том числе ``None``, означает «уже искали, результата нет»:
    повторного запроса в БД не будет. Отсутствие ключа — поиск с записью
    результата. Кэш — не второй источник истины, а только снимок ответов
    этой функции на время батча.
    """
    if code is not None:
        if code_cache is not None and code in code_cache:
            found = code_cache[code]
        else:
            found = await find_route_by_code(db, code, only_active=only_active)
            if code_cache is not None:
                code_cache[code] = found
        if found is not None:
            return RouteIdentityMatch(found, MATCH_BY_CODE)
    if name:
        if name_cache is not None and name in name_cache:
            found = name_cache[name]
        else:
            found = await find_route_by_name(
                db, name, legacy_name_only=True, only_active=only_active
            )
            if name_cache is not None:
                name_cache[name] = found
        if found is not None:
            return RouteIdentityMatch(found, MATCH_BY_LEGACY_NAME)
    return None
