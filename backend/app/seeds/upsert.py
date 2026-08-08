"""Table-driven идемпотентный upsert по ключу (ADR-0010).

Один общий хелпер для скалярных седеров: «данные → field_map → upsert».
Выполняет select по ключу, insert/update, возвращает ``dict[key, Model]``.
Составные ключи (SectionOperation: section_id + operation_code) разрешены;
производные поля (FK-резолв, transforms_dimensions) вычисляются до вызова
через опциональный ``resolve``-хук и не раздувают контракт хелпера.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")
KeyT = TypeVar("KeyT")


def _get_value(row: Any, key: str) -> Any:
    """Достаёт значение из dict-строки или объекта с атрибутами."""
    if isinstance(row, dict):
        return row[key]
    return getattr(row, key)


async def upsert_by_key(
    db: AsyncSession,
    Model: type[ModelT],
    rows: Iterable[Any],
    *,
    key_field: str | tuple[str, ...],
    field_map: Mapping[str, str],
    resolve: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[KeyT, ModelT]:
    """Идемпотентный upsert записей ``Model`` по ключу.

    Для каждой строки из ``rows`` (dict или объект с атрибутами):
    - значения ORM-полей берутся из ``field_map`` (ORM-атрибут → ключ в строке);
    - ``resolve``-хук добавляет производные поля (FK-резолв, вычисленные
      значения), если передан;
    - запись ищется по ``key_field`` (строка или кортеж — составной ключ);
    - отсутствующая запись создаётся, существующая обновляется.

    Returns:
        ``dict[key, Model]`` — ключ равен значению ``key_field`` строки.
    """
    key_fields = (key_field,) if isinstance(key_field, str) else tuple(key_field)

    result: dict[KeyT, ModelT] = {}

    for row in rows:
        values: dict[str, Any] = {
            orm_attr: _get_value(row, data_key)
            for orm_attr, data_key in field_map.items()
        }
        if resolve is not None:
            values.update(resolve(row))

        key: Any
        if len(key_fields) == 1:
            key = values[key_fields[0]]
        else:
            key = tuple(values[f] for f in key_fields)

        existing = await db.scalar(
            select(Model).where(
                *[getattr(Model, f) == values[f] for f in key_fields]
            )
        )

        if existing is None:
            obj = Model(**values)
            db.add(obj)
            await db.flush()
        else:
            for attr, value in values.items():
                setattr(existing, attr, value)
            obj = existing

        result[key] = obj

    await db.flush()
    return result
