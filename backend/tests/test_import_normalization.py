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
    match_sku_numeric,
    match_sku_parts,
    numeric_sku_key,
    sku_compound_parts,
    sku_entry,
    sku_loose,
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


# ─── Числовой ключ без ведущих нулей (#444) ──────────────────────────────────


def test_numeric_key_ignores_leading_zeros_only_for_digits():
    assert numeric_sku_key("033") == "33"
    assert numeric_sku_key(" 33 ") == "33"
    assert numeric_sku_key("0033") == "33"
    assert numeric_sku_key("0") == "0"
    assert numeric_sku_key("000") == "0"
    # Буквы, дефис и слэш — не числовой артикул: префикс значим.
    assert numeric_sku_key("ЮП-033") is None
    assert numeric_sku_key("ALS1359") is None
    assert numeric_sku_key("33/033") is None
    assert numeric_sku_key("") is None


def test_entry_numeric_key_is_derived_from_own_sku_only():
    assert sku_entry("033").numeric_key == "33"
    assert sku_entry("ЮП-033").numeric_key is None
    # Алиас чужого артикула не превращает «ЮП-033» в числовой «33».
    assert sku_entry("ЮП-033", {"33"}).numeric_key is None


def test_numeric_key_finds_product_with_leading_zeros():
    product = sku_entry("033")
    match = match_sku_cell("33", _catalog("033", "ЮП-1875"))
    assert (match.index, match.numeric_key, match.part) == (0, "33", None)
    assert match_sku_numeric("33", [product]).index == 0


def test_numeric_key_matches_when_cell_has_leading_zeros():
    assert match_sku_cell("031", _catalog("31")).index == 0
    assert match_sku_cell("033", _catalog("33")).index == 0


def test_prefixed_sku_is_not_numeric():
    # «ЮП-033» и «033» — разные артикулы: ведущие нули значимы при префиксе.
    assert not match_sku_cell("ЮП-033", _catalog("033")).found
    assert not match_sku_cell("033", _catalog("ЮП-033")).found
    assert not match_sku_cell("ЮП-33", _catalog("ЮП-033")).found


def test_two_numeric_spellings_are_ambiguous_not_chosen():
    # Ни одна запись не совпала точно: числовой ключ общий, выбирать нельзя.
    match = match_sku_cell("0033", _catalog("33", "033"))
    assert match.rejected and not match.found
    assert match.ambiguous_indexes == (0, 1)
    assert match.numeric_key == "33"


def test_exact_spelling_wins_over_numeric_key():
    entries = _catalog("33", "033")
    assert match_sku_cell("33", entries).index == 0
    assert match_sku_cell("033", entries).index == 1


def test_numeric_key_does_not_touch_non_numeric_skus():
    assert not match_sku_cell("ALS33", _catalog("ALS-033")).found
    assert not match_sku_cell("ALS-33", _catalog("ALS-033")).found
    # Нормализованное совпадение нечислового артикула работает как раньше.
    assert match_sku_cell("als–33", _catalog("ALS-33")).index == 0


def test_sku_loose_drops_dash_only_between_letter_and_digits():
    assert sku_loose("ALS-1291") == "als1291"
    assert sku_loose("ЮП–081") == "юп081"
    assert sku_loose("ALS1291") == "als1291"
    # Дефис между цифрами — часть номера, его не трогаем.
    assert sku_loose("12-34") == "12-34"


def test_dashless_spelling_matches_sku():
    # 1С пишет код поставщика без дефиса: ALS1291 — тот же ALS-1291.
    assert match_sku_cell("ALS1291", _catalog("ALS-1291")).index == 0
    assert match_sku_cell("als-1291", _catalog("ALS1291")).index == 0
    # Другой номер и дефис внутри цифр по-прежнему не склеиваются.
    assert not match_sku_cell("ALS1292", _catalog("ALS-1291")).found
    assert not match_sku_cell("12-34", _catalog("1234")).found
