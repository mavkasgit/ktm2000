"""Доменный модуль «габариты» (dimensions) — фундамент склада/плана/заданий.

Контракт (CONTEXT.md → «Габариты», ADR-0001): габариты — это
``dict | None`` в форме JSONB, например ``{"length_mm": 2700}``;
``None`` = «безразмерные штуки». Баланс группируется по
``product + section + dimensions``, поэтому у габаритов есть единая
**каноническая форма** — стабильный порядок ключей, нормализованные
значения — чтобы сравнение и группировка не зависели от того, как
именно словарь был собран.

Модуль чистый: без SQLAlchemy/FastAPI/Pydantic, без БД.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

# Каноничный ключ длины (справочник dimension_types, ADR-0001).
LENGTH_MM = "length_mm"

# Прочерк для безразмерных позиций в UI.
DIMENSIONLESS_LABEL = "—"

# Любые пробельные символы, включая NBSP/узкий NBSP из Excel —
# разделители тысяч и случайные пробелы вокруг числа.
_WHITESPACE_RE = re.compile(r"\s+")


class DimensionsValidationError(ValueError):
    """Нарушение доменных правил габаритов.

    Поднимается на невалидном входе (нулевая/отрицательная длина,
    мусорная строка из Excel и т.п.) — никаких silent ``None``.
    """


def parse_dimensions_filter(raw: str | None) -> tuple[bool, dict[str, Any] | None]:
    """Разобрать query-параметр ``dimensions`` (JSON-строка) в канонический габарит.

    Возвращает ``(active, dims)``:
    - ``(False, None)`` — параметр отсутствует/пустой, фильтр не применять;
    - ``(True, None)`` — ``"null"``, фильтр «безразмерные штуки»;
    - ``(True, dict)`` — JSON-объект, фильтр точного совпадения по габариту.

    Мусор (не JSON, не объект) → :class:`DimensionsValidationError` — вызывающий
    превращает в HTTP 422.
    """
    if raw is None or not raw.strip():
        return False, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DimensionsValidationError(
            f"Некорректный dimensions, ожидался JSON-объект или null: {raw!r}"
        ) from exc
    if value is None:
        return True, None
    if not isinstance(value, Mapping):
        raise DimensionsValidationError(
            f"dimensions должен быть JSON-объектом или null, получено: {raw!r}"
        )
    return True, canonicalize_dimensions(value)


def canonicalize_dimensions(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Привести габариты к канонической форме для хранения/сравнения/группировки.

    Правила:
    - ``None`` остаётся ``None`` (безразмерные штуки), пустой dict → ``None``;
    - ключи — непустые строки (``"length_mm"``), порядок стабильный (сортировка);
    - числовые значения нормализуются: ``2700.0`` → ``2700`` (int где возможно),
      ноль/отрицательные/не-finite → :class:`DimensionsValidationError`;
    - нечисловые значения (лишние ключи вроде ``"grade": "A"``) сохраняются как есть.

    Вход не мутируется — возвращается новый dict.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise DimensionsValidationError(
            f"Габариты должны быть dict или None, получено: {type(raw).__name__}"
        )
    if not raw:
        return None

    canonical: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise DimensionsValidationError(
                f"Ключ габарита должен быть непустой строкой, получено: {key!r}"
            )
        canonical[key] = _canonicalize_value(key, value)
    return {key: canonical[key] for key in sorted(canonical)}


def parse_length_m_to_mm(raw: str | int | float) -> int:
    """Распарсить длину из Excel: строка/число в **метрах** → целые **миллиметры**.

    Поддерживаются запятая и точка как десятичный разделитель, пробелы
    (включая NBSP) как разделители тысяч: ``"2,7"`` → 2700, ``"2.75"`` → 2750,
    ``" 1 350 "`` → 1 350 000. Мусор («abc», пустая строка), ноль и
    отрицательные значения → :class:`DimensionsValidationError`.
    """
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise DimensionsValidationError(
            f"Длина должна быть строкой или числом, получено: {raw!r}"
        )

    if isinstance(raw, str):
        text = _WHITESPACE_RE.sub("", raw).replace(",", ".")
        if not text:
            raise DimensionsValidationError("Длина не указана (пустая строка)")
        try:
            meters = float(text)
        except ValueError:
            raise DimensionsValidationError(
                f"Не удалось распознать длину в метрах: {raw!r}"
            ) from None
    else:
        meters = float(raw)

    if not math.isfinite(meters):
        raise DimensionsValidationError(f"Длина должна быть конечным числом: {raw!r}")
    if meters <= 0:
        raise DimensionsValidationError(
            f"Длина должна быть положительной, получено: {raw!r}"
        )

    mm = round(meters * 1000)
    if mm <= 0:
        raise DimensionsValidationError(
            f"Длина {raw!r} меньше 1 мм — слишком мала для учёта"
        )
    return mm


def dimensions_equal(
    a: Mapping[str, Any] | None, b: Mapping[str, Any] | None
) -> bool:
    """Сравнить два габарита на равенство через каноническую форму.

    ``{"length_mm": 2700.0}`` == ``{"length_mm": 2700}``; порядок ключей
    не важен; ``None`` == ``{}`` (оба — безразмерные).
    """
    return canonicalize_dimensions(a) == canonicalize_dimensions(b)


def format_dimensions(dims: Mapping[str, Any] | None) -> str:
    """Отформатировать габариты для UI.

    ``{"length_mm": 2700}`` → «2,7 м» (запятая как десятичный разделитель,
    без хвостовых нулей: 900 → «0,9 м», 1000 → «1 м»); ``None``/пустой
    dict → «—». Прочие наборы ключей — fallback «ключ: значение» в
    каноническом порядке.
    """
    canonical = canonicalize_dimensions(dims)
    if canonical is None:
        return DIMENSIONLESS_LABEL
    if set(canonical) == {LENGTH_MM}:
        return f"{_format_mm_as_meters(canonical[LENGTH_MM])} м"
    return ", ".join(f"{key}: {value}" for key, value in canonical.items())


def format_quantity(value: Any) -> str:
    """Количество для UI без хвостовых нулей: ``150.000`` → «150»."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _quantity_decimal(value: Any) -> Decimal:
    """Количество выхода в Decimal для слияния; мусор/None → 0."""
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def format_cut_layout(
    input_dimensions: Mapping[str, Any] | None,
    outputs: list[Mapping[str, Any]] | None,
) -> dict[str, Any] | None:
    """Раскрой позиции частями для двухколоночного показа (ADR-0002/0003):
    ``{"input": "2,75", "outputs": ["0,9×50", "1,35×100"]}`` — UI рисует вход
    со стрелкой слева, распилы столбиком справа.

    ``input`` — габарит входа без единицы; когда реальной трансформации нет,
    в ``input`` уходит одиночная подпись с единицей («2,75 м»), а ``outputs``
    пуст. Габаритные выходы сливаются по длине (количества суммируются) и идут
    по возрастанию длины; выход той же длины, что и вход, не выбрасывается.
    Безразмерные выходы печатаются как «<кол-во> шт» после габаритных в
    исходном порядке. Количества входа здесь нет — оно показывается отдельной
    колонкой UI.

    ``None``, когда габаритов нет вовсе (вход без габаритов и все выходы
    без габаритов).
    """
    entries = list(outputs or [])
    dimensioned = [
        entry for entry in entries
        if canonicalize_dimensions(entry.get("dimensions")) is not None
    ]
    dimensionless = [
        entry for entry in entries
        if canonicalize_dimensions(entry.get("dimensions")) is None
    ]
    input_has_dims = canonicalize_dimensions(input_dimensions) is not None

    if not input_has_dims and not dimensioned:
        return None

    # Реальной трансформации нет — показываем только вход одной подписью:
    # либо выходов нет, либо все габаритные выходы совпадают с входом и
    # безразмерных выходов тоже нет.
    if input_has_dims and not dimensionless and (
        not dimensioned
        or all(
            dimensions_equal(input_dimensions, entry.get("dimensions"))
            for entry in dimensioned
        )
    ):
        return {"input": format_dimensions(input_dimensions), "outputs": []}

    # Габаритные выходы: слияние по длине, сортировка по возрастанию.
    merged: dict[Decimal, Decimal] = {}
    other_parts: list[str] = []
    for entry in dimensioned:
        length = _entry_length_mm(entry.get("dimensions"))
        if length is None:
            # Нестандартный (не длинномерный) габарит — печатаем без слияния.
            other_parts.append(
                f"{_format_dimensions_without_unit(entry.get('dimensions'))}"
                f"×{format_quantity(_quantity_decimal(entry.get('quantity')))}"
            )
            continue
        merged[length] = merged.get(length, Decimal(0)) + _quantity_decimal(
            entry.get("quantity")
        )

    output_parts = [
        f"{_format_mm_as_meters(length)}×{format_quantity(merged[length])}"
        for length in sorted(merged)
    ]
    output_parts.extend(other_parts)
    output_parts.extend(
        f"{format_quantity(_quantity_decimal(entry.get('quantity')))} шт"
        for entry in dimensionless
    )

    return {
        "input": (
            _format_dimensions_without_unit(input_dimensions) if input_has_dims else None
        ),
        "outputs": output_parts,
    }


def _canonicalize_value(key: str, value: Any) -> Any:
    """Нормализовать одно значение габарита (bool — не число!)."""
    if isinstance(value, bool) or value is None:
        raise DimensionsValidationError(
            f"Значение габарита {key!r} должно быть числом или строкой, получено: {value!r}"
        )
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise DimensionsValidationError(
                f"Значение габарита {key!r} должно быть конечным числом: {value!r}"
            )
        if value <= 0:
            raise DimensionsValidationError(
                f"Значение габарита {key!r} должно быть положительным, получено: {value!r}"
            )
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    # Лишние (нечисловые) ключи сохраняются как есть.
    return value


def _format_mm_as_meters(mm: int | float | Decimal) -> str:
    """Миллиметры → строка в метрах без хвостовых нулей, с запятой: 2750 → «2,75»."""
    meters = (Decimal(str(mm)) / Decimal(1000)).normalize()
    return format(meters, "f").replace(".", ",")


def _format_dimensions_without_unit(dims: Mapping[str, Any] | None) -> str:
    """Как :func:`format_dimensions`, но без суффикса единицы: 2750 → «2,75».

    Используется внутри строки раскроя, где единица не нужна: подписи входа
    и габаритных выходов соседствуют, а единицы разных позиций могут быть
    разными.
    """
    canonical = canonicalize_dimensions(dims)
    if canonical is None:
        return DIMENSIONLESS_LABEL
    if set(canonical) == {LENGTH_MM}:
        return _format_mm_as_meters(canonical[LENGTH_MM])
    return ", ".join(f"{key}: {value}" for key, value in canonical.items())


def _entry_length_mm(dims: Mapping[str, Any] | None) -> Decimal | None:
    """Длина габарита в мм для сортировки/слияния, либо ``None``."""
    canonical = canonicalize_dimensions(dims)
    if canonical is None or LENGTH_MM not in canonical:
        return None
    return Decimal(str(canonical[LENGTH_MM]))
