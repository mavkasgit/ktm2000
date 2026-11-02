from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_IMPORT_NORMALIZATION_RULES: dict[str, Any] = {}

# Варианты написания тире (unicode-дефисы, минус, широкий дефис и т.п.),
# которые при нормализации артикула сводятся к обычному ``-``.
_SKU_DASH_VARIANTS = "\u2010\u2011\u2012\u2013\u2014\u2212\u2043\uFE58\uFE63\uFF0D"


def normalize_sku(value: str) -> str:
    """Нормализация артикула для сравнения/поиска.

    Приводит к нижнему регистру, срезает пробелы, унифицирует все варианты
    тире в обычный ``-`` и убирает все пробелы (включая неразрывный).
    """
    normalized = (value or "").strip().lower()
    for ch in _SKU_DASH_VARIANTS:
        normalized = normalized.replace(ch, "-")
    return normalized.replace(" ", "").replace("\u00A0", "")


_SKU_COMPOUND_SEPARATOR = "/"


def sku_compound_parts(value: str | None) -> list[str]:
    """Нормализованные части составного артикула по ``/``, в порядке ячейки.

    Меньше двух непустых частей — артикул не составной: у ``ЮП-3658/`` иначе
    появлялась бы одна «часть», и строка получила бы ложное предупреждение.
    """
    if not value or _SKU_COMPOUND_SEPARATOR not in value:
        return []
    parts: list[str] = []
    for chunk in value.split(_SKU_COMPOUND_SEPARATOR):
        part = normalize_sku(chunk)
        if part and part not in parts:
            parts.append(part)
    return parts if len(parts) > 1 else []


def sku_tail(sku: str) -> str:
    """Хвост артикула после последнего тире: ``ЮП-1875`` → ``1875``.

    У SKU без тире хвостом считается весь артикул: сравнение части с ним и так
    покрыто точным совпадением, отдельного правила не нужно.
    """
    normalized = normalize_sku(sku)
    _, separator, tail = normalized.rpartition("-")
    return tail if separator and tail else normalized


def default_import_normalization_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_IMPORT_NORMALIZATION_RULES)


def has_valid_normalization_rules(value: Any) -> bool:
    """Normalization rules are deprecated — always return False."""
    return False


def apply_import_normalization(
    *,
    raw_operation: str | None,
    raw_output_kind: str | None,
    normalization_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    """No-op — normalization is handled by route selection rules now."""
    return {
        "operation_code": None,
        "operation_name": None,
        "additional_pack_operations": [],
        "normalized_pack_op_family": "NONE",
        "output_kind": raw_output_kind,
    }


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
