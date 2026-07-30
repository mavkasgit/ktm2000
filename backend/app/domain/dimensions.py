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

import math
import re
from collections.abc import Mapping
from decimal import Decimal
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


def format_operation_summary(
    input_quantity: Any | None,
    input_dimensions: Mapping[str, Any] | None,
    outputs: list[Mapping[str, Any]] | None,
) -> str | None:
    """Сводка операции «вход → все выходы» для UI (ADR-0002/0003):
    «150 шт × 2,7 м → 150 × 0,9 м + 150 × 1,8 м».

    ``None``, если выходов нет или операция полностью безразмерная —
    показывать нечего.
    """
    entries = list(outputs or [])
    has_dimensions = bool(input_dimensions) or any(
        entry.get("dimensions") for entry in entries
    )
    if not entries or not has_dimensions:
        return None
    input_parts: list[str] = []
    if input_quantity is not None:
        input_parts.append(f"{format_quantity(input_quantity)} шт")
    if input_dimensions:
        input_parts.append(format_dimensions(input_dimensions))
    output_parts: list[str] = []
    for entry in entries:
        qty = format_quantity(entry.get("quantity") or "0")
        dims = entry.get("dimensions")
        output_parts.append(f"{qty} × {format_dimensions(dims)}" if dims else f"{qty} шт")
    outputs_text = " + ".join(output_parts)
    if not input_parts:
        return outputs_text
    return f"{' × '.join(input_parts)} → {outputs_text}"


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


def _format_mm_as_meters(mm: int | float) -> str:
    """Миллиметры → строка в метрах без хвостовых нулей, с запятой: 2750 → «2,75»."""
    meters = (Decimal(str(mm)) / Decimal(1000)).normalize()
    return format(meters, "f").replace(".", ",")
