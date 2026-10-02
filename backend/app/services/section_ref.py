"""Плоская проекция участка для маршрутных сервисов (#303).

Маршрутные сервисы читают из участка ровно четыре поля: ``id``, ``code``,
``name`` и ``type``. Последнее нужно классификатору
(:func:`app.services.route_storage_classifier.is_storage_section`), остальное —
для сборки шагов маршрута и диагностики подбора.

Загрузка ORM-``Section`` стоит четырёх запросов, а не одного: у модели три
связи с ``lazy="selectin"`` (``users``, ``operations``, ``spg_links``), и они
срабатывают на каждый загруженный экземпляр. В списках позиций участки
читаются на каждой строке, поэтому это самый дорогой остаток после #297/#298/#296.

:class:`SectionRef` закрывает контракт: классификаторы и потребители читают
``.type`` / ``.code`` / ``.name`` / ``.id``, объект ORM им не нужен. Ничего,
кроме этих четырёх полей, проекция не обещает — если кому-то понадобится
настоящий ``Section`` (например, ``is_active``), он должен явно взять его
отдельным запросом, а не получить молчаливо неполный объект.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section

#: Поля, которые проекция вообще несёт. Всё, что читается из участка в
#: маршрутных сервисах, должно быть здесь — иначе это не проекция, а
#: «случайно досталось из ORM-объекта».
SECTION_REF_COLUMNS = (Section.id, Section.code, Section.name, Section.type)


@dataclass(frozen=True, slots=True)
class SectionRef:
    """Участок как плоские значения: ровно четыре поля маршрутов."""

    id: int
    code: str
    name: str
    type: str


async def load_section_refs(
    db: AsyncSession,
    *,
    ids: set[int] | None = None,
    codes: set[str] | None = None,
) -> dict[int, SectionRef]:
    """Прочитать участки по id и/или кодам — одним запросом по колонкам.

    Возвращает словарь по ``id``. Пустой набор фильтров читает все участки
    (тот случай, который раньше стоил четырёх запросов на каждый вызов).
    """
    stmt = select(*SECTION_REF_COLUMNS)
    if ids:
        stmt = stmt.where(Section.id.in_(ids))
    if codes:
        stmt = stmt.where(Section.code.in_(codes))
    return {
        row.id: SectionRef(id=row.id, code=row.code, name=row.name, type=row.type)
        for row in (await db.execute(stmt)).all()
    }
