"""Разбор составного артикула из ячейки импорта (#347, ADR-0067).

Ячейка вида «ЮП-3658/1875» не является SKU справочника: справочник хранит
оба артикула отдельно. Помощники ниже — единственное место, где решается,
какие части такой ячейки вообще имеют смысл для сопоставления; сам выбор
артикула из частей делают импорты (остатки, план).
"""
from __future__ import annotations

from app.services.import_normalization import (
    sku_compound_parts,
    sku_tail,
)


def test_compound_parts_keeps_cell_order():
    assert sku_compound_parts("ЮП-3658/1875") == ["юп-3658", "1875"]
    assert sku_compound_parts("1875/ЮП-3658") == ["1875", "юп-3658"]


def test_compound_parts_normalizes_dashes_case_and_spaces():
    # Типографское тире, неразрывный пробел и верхний регистр — то же значение.
    assert sku_compound_parts("ЮП–3658 / юп 1875") == ["юп-3658", "юп1875"]
    assert sku_compound_parts("ЮП\u00A03658/1875") == ["юп3658", "1875"]


def test_compound_parts_requires_two_non_empty_parts():
    # Одиночный артикул — не составной: ложного «матча по части» быть не должно.
    assert sku_compound_parts("ЮП-3658") == []
    assert sku_compound_parts("ЮП-3658/") == []
    assert sku_compound_parts("/1875") == []
    assert sku_compound_parts("A//B") == ["a", "b"]
    assert sku_compound_parts("ЮП-3658/ЮП-3658") == []
    assert sku_compound_parts(None) == []
    assert sku_compound_parts("") == []


def test_compound_parts_supports_more_than_two_parts():
    assert sku_compound_parts("ЮП-1/ЮП-2/ЮП-3") == ["юп-1", "юп-2", "юп-3"]


def test_tail_is_text_after_last_dash():
    assert sku_tail("ЮП-1875") == "1875"
    assert sku_tail("юп-2616") == "2616"
    # Хвост считается от ПОСЛЕДНЕГО тире.
    assert sku_tail("ЮП-1875-2") == "2"
    assert sku_tail("1875") == "1875"
    assert sku_tail("ALS1289") == "als1289"


def test_tail_matches_part_through_normalization():
    # Контракт импортов: part == normalize_sku(sku) or part == sku_tail(sku).
    part = sku_compound_parts("ЮП-3658/1875")[1]
    assert part == sku_tail("ЮП–1875")
    assert part != sku_tail("ЮП 1875")  # без тире хвоста нет — это весь SKU
    assert part != sku_tail("ЮП-1876")
