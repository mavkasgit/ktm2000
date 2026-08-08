"""Резолвер колонок Excel по данным шаблона ImportTemplate (#15).

Единый модуль сопоставления колонок для импорта плана (``excel_import``) и
остатков (``stock/import_service``): заголовки, псевдонимы и позиции колонок
приходят из данных шаблона (``column_mapping`` сида), а не захардкожены в коде.

Контракт::

    resolve_columns(template_mapping, header_row) -> dict[str, int]

- ``template_mapping`` — ``column_mapping`` из ``ImportTemplate`` (данные);
- ``header_row`` — фактические заголовки листа (``None`` → позиционный режим).

Если строка заголовков задана и распознана — сопоставление по заголовкам
шаблона (и псевдонимам). Иначе — позиционный режим из порядка колонок
шаблона (буквы ``column`` в данных).
"""
from __future__ import annotations

from typing import Any

# Служебные ключи ``column_mapping`` (начинаются с ``_``) не описывают
# колонку: ``_config`` несёт метаданные шаблона (флаг обязательности длины
# для остатков).
RESERVED_PREFIX = "_"


def is_reserved_key(key: str) -> bool:
    """True для служебных ключей шаблона, которые не являются колонками."""
    return str(key).startswith(RESERVED_PREFIX)


def _norm(value: str) -> str:
    """Нормализация заголовка: lowercase, схлопывание пробелов/ nbsps."""
    return " ".join(str(value).lower().replace("\xa0", " ").split())


def _col_letter_to_index(letter: str) -> int | None:
    """'A' -> 0, 'B' -> 1, …; пустая/невалидная строка -> None."""
    text = str(letter or "").strip().upper()
    if not text:
        return None
    index = 0
    for ch in text:
        if not ("A" <= ch <= "Z"):
            return None
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _field_configs(template_mapping: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Нормализованные конфиги колонок (служебные ключи пропускаются).

    Старый строковый формат (``field: "Заголовок"``) приводится к
    ``{"header": "Заголовок"}``.
    """
    result: dict[str, dict[str, Any]] = {}
    for field, cfg in (template_mapping or {}).items():
        key = str(field).strip()
        if not key or is_reserved_key(key):
            continue
        if isinstance(cfg, dict):
            result[key] = cfg
        else:
            result[key] = {"header": str(cfg)}
    return result


def _headers_for(cfg: dict[str, Any]) -> list[str]:
    """Канонический заголовок + псевдонимы колонки."""
    headers: list[str] = []
    raw_header = cfg.get("header")
    if raw_header is not None:
        headers.append(str(raw_header))
    aliases = cfg.get("aliases")
    if aliases is None:
        return headers
    if isinstance(aliases, str):
        aliases = [aliases]
    for alias in aliases:
        if alias is not None and str(alias).strip():
            headers.append(str(alias))
    return headers


def _field_norm_headers(cfg: dict[str, Any]) -> set[str]:
    return {_norm(h) for h in _headers_for(cfg) if _norm(h)}


def _row_recognized(header_row: list[str] | None, field_configs: dict[str, dict[str, Any]]) -> bool:
    """Распознана ли строка как строка заголовков шаблона."""
    if not header_row:
        return False
    normed = {_norm(h) for h in header_row if _norm(h)}
    if not normed:
        return False
    for cfg in field_configs.values():
        if _field_norm_headers(cfg) & normed:
            return True
    joined = _norm("".join(header_row))
    return "артикул" in joined and ("операц" in joined or "выполнен" in joined)


def detect_header_row(
    rows: list[list[Any]],
    template_mapping: dict[str, Any] | None,
    scan_limit: int = 10,
) -> int | None:
    """Индекс строки заголовков по данным шаблона, либо None (позиционный режим)."""
    field_configs = _field_configs(template_mapping)
    for idx, row in enumerate(rows[:scan_limit]):
        if _row_recognized([str(cell) for cell in row], field_configs):
            return idx
    return None


def resolve_columns(
    template_mapping: dict[str, Any] | None,
    header_row: list[str] | None,
) -> dict[str, int]:
    """field -> индекс колонки.

    ``header_row`` задан и распознан → сопоставление по заголовкам шаблона
    (и псевдонимам). ``None`` либо нераспознанная строка → позиционный режим
    из порядка колонок шаблона (буквы ``column`` в данных).
    """
    field_configs = _field_configs(template_mapping)
    if not field_configs:
        return {}
    if header_row is not None and _row_recognized(header_row, field_configs):
        return _resolve_by_headers(header_row, field_configs)
    return _resolve_positional(field_configs)


def _resolve_by_headers(
    header_row: list[str],
    field_configs: dict[str, dict[str, Any]],
) -> dict[str, int]:
    result: dict[str, int] = {}
    normed_headers = [_norm(h) for h in header_row]
    for field, cfg in field_configs.items():
        target = _field_norm_headers(cfg)
        for index, normed in enumerate(normed_headers):
            if normed and normed in target:
                result[field] = index
                break
    # Совместимость: одна колонка без распознанного артикула — артикул в ней.
    if "sku" not in result and len(header_row) == 1:
        result["sku"] = 0
    return result


def _resolve_positional(field_configs: dict[str, dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for field, cfg in field_configs.items():
        column = cfg.get("column")
        index = _col_letter_to_index(str(column) if column is not None else "")
        if index is not None:
            result[field] = index
    return result
