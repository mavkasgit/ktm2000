"""Тикет #16: политика завода в данные — поведение не изменилось.

Проверки, что правила, перенесённые из кода в справочник политик завода,
дают те же результаты на текущем наборе данных.
"""

from __future__ import annotations

from decimal import Decimal

from app.seeds.plant_policies import (
    COLOR_TOKENS,
    HANGER_ROUNDING_RULE,
    PAIRED_PROCESSING_VALUE,
    VALIDATION_ERROR_MESSAGES,
)
from app.services.color_extraction import extract_color_from_text, resolve_payload_color
from app.services.hanger_quantity import adjust_quantity_to_hanger
from app.services.plan_validation import format_validation_error

EXPECTED_COLOR_TOKENS: list[tuple[str, str]] = [
    ("анод.серебро", "серебро"),
    ("анодсеребро", "серебро"),
    ("анодчёрный", "черный"),
    ("анодчерный", "черный"),
    ("анодшампань", "шампань"),
    ("анодтитан", "титан"),
    ("анодзолото", "золото"),
    ("анодбронза", "бронза"),
    ("анодмедь", "медь"),
    ("анодмед", "медь"),
]


class TestColorTokensFromData:
    """Токены цветов заданы данными; извлечение работает как раньше."""

    def test_color_tokens_live_in_plant_policies_data(self) -> None:
        tokens = [(item["token"], item["color"]) for item in COLOR_TOKENS]
        assert tokens == EXPECTED_COLOR_TOKENS

    def test_color_tokens_removed_from_code_module(self) -> None:
        assert not hasattr(__import__("app.services.color_extraction", fromlist=["_COLOR_TOKENS"]), "_COLOR_TOKENS")

    def test_extraction_behavior_unchanged_for_current_data(self) -> None:
        assert extract_color_from_text("РП-АКТ-03 2,7 м анодтитан матов") == "титан"
        assert extract_color_from_text("РП-АКТ-03 2,7 м анодчерный матов") == "черный"
        assert extract_color_from_text("РП-АКТ-03 2,7 м анодчёрный матов") == "черный"
        assert extract_color_from_text("Стык 38 мм. 2,7 анод.серебро, матовый") == "серебро"
        assert extract_color_from_text("Профиль анодшампань глянец") == "шампань"
        assert extract_color_from_text("Профиль анодзолото") == "золото"
        assert extract_color_from_text("Профиль анодбронза") == "бронза"
        assert extract_color_from_text("Профиль анодмедь матовый") == "медь"
        assert extract_color_from_text("Профиль анодмед матовый") == "медь"
        assert extract_color_from_text("Профиль анодсеребро") == "серебро"
        assert extract_color_from_text("Без цветового токена") is None

    def test_resolve_payload_color_behavior_unchanged(self) -> None:
        assert resolve_payload_color("серебро", "… анодтитан …") == "серебро"
        assert resolve_payload_color(None, "… анодшампань …") == "шампань"
        assert resolve_payload_color("анодсеребро/анодтитан/анодчерный", None) == "черный"
        assert resolve_payload_color("серебро/анодтитан", None) == "титан"


class TestValidationErrorMessagesFromData:
    """Тексты ошибок валидации — данные; fallback на код сохранён."""

    def test_messages_live_in_plant_policies_data(self) -> None:
        assert VALIDATION_ERROR_MESSAGES["product_not_found"] == "Продукт не найден"
        assert VALIDATION_ERROR_MESSAGES["route_primary_operation_mismatch"].startswith(
            "Основная операция маршрута"
        )

    def test_format_validation_error_reads_text_from_data(self) -> None:
        assert format_validation_error("product_not_found") == "Продукт не найден"

    def test_format_validation_error_fallback_to_code(self) -> None:
        assert format_validation_error("unknown_error_code") == "unknown_error_code"

    def test_format_validation_error_with_detail(self) -> None:
        assert (
            format_validation_error("product_not_found: SKU-123")
            == "Продукт не найден (SKU-123)"
        )


class TestPairedProcessingValueFromData:
    """Признак парной обработки читается из данных."""

    def test_paired_processing_value_lives_in_plant_policies(self) -> None:
        assert PAIRED_PROCESSING_VALUE == "paired_processing"


class TestHangerRoundingRuleFromData:
    """Правило округления до подвески настраивается данными."""

    def test_rule_lives_in_plant_policies(self) -> None:
        assert HANGER_ROUNDING_RULE == {"enabled": True, "mode": "round_up_to_multiple"}

    def test_rounding_behavior_unchanged_for_current_data(self) -> None:
        assert adjust_quantity_to_hanger(Decimal("12"), 5) == Decimal("15")
        assert adjust_quantity_to_hanger(Decimal("10"), 5) is None
        assert adjust_quantity_to_hanger(Decimal("12"), None) is None
        assert adjust_quantity_to_hanger(Decimal("12.5"), 5) == Decimal("15")
