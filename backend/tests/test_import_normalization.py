"""Разбор и сопоставление составного артикула из ячейки импорта (#347, ADR-0067).

Ячейка вида «ЮП-3658/1875» не является SKU справочника: справочник хранит оба
артикула отдельно. Здесь и разбор на части, и каскад привязки «целая ячейка →
части» — общий для импортов остатков и плана; импорты выбирают только запись
справочника (свои ключи поиска) и решают, что делать с неоднозначностью.
"""
from __future__ import annotations

from app.services.import_normalization import (
    SkuEntry,
    match_sku_cell,
    match_sku_parts,
    sku_compound_parts,
    sku_entry,
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


# ─── Каскад привязки ─────────────────────────────────────────────────────────


def _catalog(*skus: str) -> list[SkuEntry]:
    return [sku_entry(sku) for sku in skus]


def test_entry_keys_include_normalized_sku_and_extra_spellings():
    entry = sku_entry("ЮП-1875", {"юз-1875"})
    assert entry.keys == frozenset({"юп-1875", "юз-1875"})
    assert entry.tail == "1875"
    # Пустое написание не становится ключом: иначе привязалась бы пустая часть.
    assert "" not in sku_entry("").keys


def test_part_matches_exact_sku_and_tail():
    entries = _catalog("ЮП-3658", "ЮП-1875")
    assert match_sku_parts("ЮП-3658/1875", entries).index == 0
    tail_hit = match_sku_parts("ХХ-9999/1875", entries)
    assert (tail_hit.index, tail_hit.part) == (1, "1875")
    assert match_sku_parts("ХХ-9999/9998", entries).index is None


def test_part_search_stops_at_first_binding_part():
    # Оба артикула в справочнике: берётся первая часть по порядку ячейки.
    match = match_sku_parts("ЮП-3658/ЮП-1875", _catalog("ЮП-3658", "ЮП-1875"))
    assert (match.index, match.part) == (0, "юп-3658")


def test_part_matching_exact_sku_of_one_and_tail_of_another_is_ambiguous():
    # «1875» — точный SKU одного артикула и хвост другого: выбирать нельзя.
    match = match_sku_parts("ХХ-9999/1875", _catalog("1875", "ЮП-1875"))
    assert match.rejected and not match.found


def test_ambiguous_part_blocks_and_skips_following_parts():
    # «1875» подходит и к «ЮП-1875», и к «АТ-1875»: третья часть не спасает.
    match = match_sku_parts("ХХ-9999/1875/ЮП-3658", _catalog("ЮП-1875", "АТ-1875"))
    assert match.rejected
    assert not match.found
    assert match.part == "1875"
    assert match.ambiguous_indexes == (0, 1)


def test_several_spellings_of_one_entry_are_not_ambiguous():
    # Ключей у артикула несколько, а запись одна: двух попаданий быть не должно.
    entries = [sku_entry("ЮП-1875", {"юп1875"}), *_catalog("ЮП-3658")]
    assert match_sku_parts("Что-то/юп-1875", entries).index == 0


def test_whole_cell_wins_over_parts():
    # Артикул со слэшем легален: привязывать его к первой части — ошибка.
    entries = _catalog("ЮП-3658/1875", "ЮП-3658", "ЮП-1875")
    match = match_sku_cell("ЮП-3658/1875", entries)
    assert match.index == 0
    assert match.part is None


def test_whole_cell_compares_normalized_spellings():
    entries = _catalog("ЮП–1875")
    assert match_sku_cell(" юп-1875 ", entries).index == 0


def test_plain_sku_never_reaches_part_cascade():
    match = match_sku_cell("ЮП-3658", _catalog("ЮП-1875"))
    assert not match.found and not match.rejected
