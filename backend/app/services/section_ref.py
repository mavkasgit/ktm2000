"""Плоская проекция участка для маршрутных сервисов (#303).

Маршрутные сервисы и список маршрутов читают из участка шесть полей:
``id``, ``code``, ``name``, ``type``, ``icon``, ``icon_color``. Первое нужно
для ключа, ``type`` — классификатору
(:func:`app.services.route_storage_classifier.is_storage_section`), остальные —
для сборки шагов маршрута и его карточки.

Загрузка ORM-``Section`` стоит четырёх запросов, а не одного: у модели три
связи с ``lazy="selectin"`` (``users``, ``operations``, ``spg_links``), и они
срабатывают на каждый загруженный экземпляр. В списках позиций участки
читаются на каждой строке, поэтому это самый дорогой остаток после
#297/#298/#296.

:class:`SectionRef` закрывает контракт: потребители читают шесть полей,
объект ORM им не нужен. Ничего сверх них проекция не обещает — если кому-то
понадобится ``is_active`` или что-то ещё, он должен взять это отдельным
запросом, а не получить молчаливо неполный объект.

Поля ``icon``/``icon_color`` добавлены при переводе ``api/routes/routes.py``:
его ``_section_step_fields`` отдаёт их в ответе, и без них проекция была бы
неполной для этой ручки.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section

#: Поля, которые проекция вообще несёт. Всё, что читается из участка в
#: маршрутных сервисах и в списке маршрутов, должно быть здесь — иначе это не
#: проекция, а «случайно досталось из ORM-объекта».
SECTION_REF_COLUMNS = (
    Section.id,
    Section.code,
    Section.name,
    Section.type,
    Section.icon,
    Section.icon_color,
)


@dataclass(frozen=True, slots=True)
class SectionRef:
    """Участок как плоские значения: шесть полей."""

    id: int
    code: str
    name: str
    type: str
    icon: str | None = None
    icon_color: str | None = None


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
        row.id: SectionRef(
            id=row.id,
            code=row.code,
            name=row.name,
            type=row.type,
            icon=row.icon,
            icon_color=row.icon_color,
        )
        for row in (await db.execute(stmt)).all()
    }
