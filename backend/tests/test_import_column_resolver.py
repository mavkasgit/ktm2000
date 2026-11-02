"""Юнит-тесты резолвера колонок Excel (issue #15).

``app/services/import_column_resolver.py`` — единый источник сопоставления
колонок (заголовки/псевдонимы/позиции) для импорта плана и остатков.
Данные берутся из ``column_mapping`` шаблона, а не из кода.
"""
from __future__ import annotations

from app.seeds.import_templates import IMPORT_TEMPLATES
from app.services.import_column_resolver import (
    detect_header_row,
    is_reserved_key,
    resolve_columns,
)
from app.stock.import_service import load_remainders_default_mapping

PLAN_MAPPING = next(
    t["column_mapping"] for t in IMPORT_TEMPLATES if t["code"] == "upakovochnaya_karta_rp"
)
# Дефолтный маппинг остатков живёт в JSON-файле, а не в сиде шаблонов
# (ADR-0003 «Обновление»).
OSTAKI_MAPPING = load_remainders_default_mapping()


# ─── Позиционный режим (header_row=None) ─────────────────────────────────────


def test_positional_mode_uses_template_column_order() -> None:
    """Без заголовков индексы берутся из порядка колонок шаблона (A..G)."""
    result = resolve_columns(OSTAKI_MAPPING, None)
    assert result == {
        "sku": 0,
        "quantity": 1,
        "quality_state": 2,
        "completed_operations": 3,
        "target_section": 4,
        "comment": 5,
        "length": 6,
    }


def test_positional_mode_plan_template_columns() -> None:
    """Позиции плана (A..T) выводятся из букв шаблона, не констант."""
    result = resolve_columns(PLAN_MAPPING, None)
    assert result["sku"] == 0
    assert result["input_quantity"] == 5
    assert result["input_length"] == 6
    assert result["output_quantity"] == 11
    assert result["add_quantity"] == 19
    assert "quantity" not in result  # план не имеет ключа quantity


def test_positional_mode_skips_reserved_and_unknown_letters() -> None:
    mapping = {"_config": {"months": {"январ": 1}}, "sku": {"column": "A"}, "comment": {"column": "F"}}
    assert resolve_columns(mapping, None) == {"sku": 0, "comment": 5}


def test_positional_mode_empty_mapping() -> None:
    assert resolve_columns(None, None) == {}
    assert resolve_columns({}, None) == {}


# ─── Заголовочный режим ──────────────────────────────────────────────────────


def test_header_mode_resolves_by_headers_and_aliases() -> None:
    headers = [
        "Артикул / SKU",  # алиас sku
        "Кол-во шт.",     # алиас quantity
        "Статус",         # качество не распознано → колонки нет
        "Выполненные операции",
        "Участок",
        "Комментарий",
        "Длина, м",
    ]
    result = resolve_columns(OSTAKI_MAPPING, headers)
    assert result["sku"] == 0
    assert result["quantity"] == 1
    assert result["completed_operations"] == 3
    assert result["target_section"] == 4
    assert result["comment"] == 5
    assert result["length"] == 6
    assert "quality_state" not in result


def test_header_mode_plan_typical_headers() -> None:
    headers = [
        "Артикул", "пополнение", "Наименование", "остатки сырья на КТМ",
        "Цвет", "кол-во шт. в 2,7", "Длина, м", "Пробивка/сверловка",
        "Упаковка", "Примечание", "Длина после упак, м",
        "кол-во штук готовой продукции", "Запад", "Восток",
        "Вид конечного продукта", "Примечание", "", "",
        "Упаковка в 1,8", "Добавить",
    ]
    result = resolve_columns(PLAN_MAPPING, headers)
    assert result["sku"] == 0
    assert result["input_length"] == 6
    assert result["output_quantity"] == 11
    assert result["add_quantity"] == 19


def test_header_mode_duplicate_headers_first_match_like_legacy() -> None:
    """Повторяющийся заголовок «Примечание» → первый match, как старый парсер."""
    headers = [f"c{i}" for i in range(16)]
    headers[9] = "Примечание"
    headers[15] = "Примечание"
    result = resolve_columns(PLAN_MAPPING, headers)
    assert result["note"] == 9
    assert result["comments"] == 9


def test_header_mode_single_column_fallback_sku() -> None:
    """Одна нераспознанная колонка → позиционный режим, артикул в колонке 0."""
    mapping = {"sku": {"column": "A", "header": "Артикул", "aliases": ["sku"]}}
    assert resolve_columns(mapping, ["ЮП-460"]) == {"sku": 0}


# ─── Детекция строки заголовков ──────────────────────────────────────────────


def test_detect_header_row_by_template_aliases() -> None:
    rows = [
        ["№", "ФИО"],
        ["Артикул", "Кол-во", "Статус качества", "Длина"],
        ["361", "200", "Годный", ""],
    ]
    assert detect_header_row(rows, OSTAKI_MAPPING) == 1


def test_detect_header_row_concatenated_header_fallback() -> None:
    """Слипшаяся строка «АртикулВыполненные операции» распознаётся."""
    rows = [["АртикулВыполненные операции", "Кол-во"], ["ЮП-460Окно, Дробеструй", "5"]]
    assert detect_header_row(rows, OSTAKI_MAPPING) == 0


def test_detect_header_row_none_when_no_headers() -> None:
    rows = [["361", "200", "Годный"], ["ALS-1289", "150", "Годный"]]
    assert detect_header_row(rows, OSTAKI_MAPPING) is None


def test_detect_header_row_none_for_empty() -> None:
    assert detect_header_row([], OSTAKI_MAPPING) is None


# ─── Резервированные ключи ───────────────────────────────────────────────────


def test_is_reserved_key() -> None:
    assert is_reserved_key("_config")
    assert is_reserved_key("_months")
    assert not is_reserved_key("sku")
    assert not is_reserved_key("quantity")


def test_plan_config_has_no_months() -> None:
    """Месяцы убраны из сида: автодетект периода больше не используется."""
    config = PLAN_MAPPING.get("_config")
    assert config is None or "months" not in config
