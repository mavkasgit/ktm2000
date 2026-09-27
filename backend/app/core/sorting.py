"""
core/sorting.py
==============

Разбор и применение сортировки строк в общем виде ``?sort=field:order,field:order``.

Единый контракт сортировки для всех эндпоинтов. Разбор строки не знает
про SQL — резолв поля в выражение это дело вызывающего (домен разный),
поэтому он передаётся таблицей ``{field: колонка}``. Применение общее:
колонки по приоритету слева направо, в конце tiebreaker, у части полей
``NULLS LAST``.

Правила (обязательны для всех эндпоинтов):

- Неизвестное поле или направление — ``400``, а не молчаливый фолбэк на
  колонку по умолчанию: кликнул «Наименование» и не видит эффекта — это
  дефект, а не поведение.
- ``NULLS LAST`` не зависит от направления: пустые значения в конец и при
  возрастании, и при убывании.
- ``tiebreaker`` дописывается последним и всегда в одном направлении.
  Он нужен ради стабильности между страницами: без него строки с равными
  значениями могут «мигать» при переходе на страницу 2 и обратно.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

DIRECTIONS = ("asc", "desc")


@dataclass(frozen=True)
class SortClause:
    """Одна колонка сортировки: поле и направление."""

    field: str
    order: str

    @property
    def is_desc(self) -> bool:
        return self.order == "desc"


def parse_sort(raw: str | None, *, default: SortClause) -> list[SortClause]:
    """Разбирает ``field:order,field:order`` в список приоритетов.

    Пустая строка — возвращается ``default`` эндпоинта. Без двоеточия
    направление ``asc`` (совпадает с поведением ``/api/products``).
    Повторяющееся поле берётся по старшему приоритету: у него уже есть
    место в списке, второй раз оно ничего не изменит.
    """
    if raw is None or not raw.strip():
        return [default]

    clauses: list[SortClause] = []
    seen: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        field, order = (part.rsplit(":", 1) if ":" in part else (part, "asc"))
        field = field.strip()
        order = order.strip().lower() or "asc"
        if not field:
            raise HTTPException(status_code=400, detail="Invalid sort: пустое поле")
        if order not in DIRECTIONS:
            raise HTTPException(status_code=400, detail=f"Invalid sort order: {order}")
        if field in seen:
            continue
        seen.add(field)
        clauses.append(SortClause(field, order))

    return clauses or [default]


def apply_sort(
    stmt: Any,
    clauses: Sequence[SortClause],
    columns: Mapping[str, Any],
    *,
    tiebreaker: Any,
    nulls_last: Iterable[str] = (),
) -> Any:
    """Добавляет к ``stmt`` ``ORDER BY`` по списку приоритетов.

    ``columns`` — таблица «поле → колонка»; значение может быть
    выражением SQLAlchemy либо callable, если колонка зависит от алиасов
    запроса (``length_mm`` у products, ``next_section`` у передач).
    Поле вне ``columns`` — ``400``: эндпоинт не умеет сортировать по нему,
    и подставлять вместо него другое поле нельзя.
    """
    nulls_last_fields = set(nulls_last)
    keys = []
    for clause in clauses:
        if clause.field not in columns:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {clause.field}")
        column = columns[clause.field]
        key = (column() if callable(column) else column)
        key = key.desc() if clause.is_desc else key.asc()
        if clause.field in nulls_last_fields:
            key = key.nulls_last()
        keys.append(key)

    # Tiebreaker всегда возрастающий: он раскладывает равные значения, но
    # не влияет на то, какая строка идёт первой среди неравных.
    keys.append(tiebreaker.asc())
    return stmt.order_by(*keys)


def sort_items(
    items: Iterable[Any],
    clauses: Sequence[SortClause],
    keys: Mapping[str, Callable[[Any], Any]],
    *,
    nulls_last: Iterable[str] = (),
    tiebreaker: Callable[[Any], Any] | None = None,
) -> list[Any]:
    """Сортирует список в Python по списку приоритетов (сортировка на диске/в памяти).

    Сортировка стабильная и применяется от младшего приоритета к старшему.
    Поле вне ``keys`` — ``400``, как и в :func:`apply_sort`.
    Для полей из ``nulls_last`` пустые значения уходят в конец независимо от
    направления: сортируются только непустые, пустые дописываются после.
    """
    nulls_last_fields = set(nulls_last)
    for clause in clauses:
        if clause.field not in keys:
            raise HTTPException(status_code=400, detail=f"Invalid sort field: {clause.field}")

    # Tiebreaker — младший приоритет: сортируем по нему первым, дальше
    # стабильные проходы по приоритетам не трогают уже выстроенный порядок
    # равных строк. В SQL это эквивалентно `ORDER BY a, b, id`.
    ordered = list(items)
    if tiebreaker is not None:
        ordered.sort(key=tiebreaker)

    for clause in reversed(clauses):
        accessor = keys[clause.field]
        if clause.field in nulls_last_fields:
            present = [item for item in ordered if accessor(item) is not None]
            missing = [item for item in ordered if accessor(item) is None]
            present.sort(key=accessor, reverse=clause.is_desc)
            ordered = present + missing
        else:
            ordered.sort(key=accessor, reverse=clause.is_desc)

    return ordered
