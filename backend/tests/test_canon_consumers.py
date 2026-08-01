"""Per-consumer тесты с fake PlantConfig (ADR-0004, тикет #22).

Проверяют, что сервисы не хардкодят значения: fake ≠ prod →
если проходит, сервис универсален.
"""

from __future__ import annotations

from decimal import Decimal

from app.seeds.canon.models import (
    ColorToken,
    HangerRoundingRule,
)
from app.services.color_extraction import extract_color_from_text, resolve_payload_color
from app.services.hanger_quantity import adjust_quantity_to_hanger
from app.services.plan_validation import format_validation_error


# ─── Fake data (отличается от prod) ──────────────────────────────────────────

FAKE_COLOR_TOKENS = [
    ColorToken(token="test.silver", color="silver"),
    ColorToken(token="testblack", color="black"),
]

FAKE_ERROR_MESSAGES = {
    "custom_error": "Custom error text",
    "another_error": "Another text",
}

FAKE_HANGER_ROUNDING_DISABLED = HangerRoundingRule(enabled=False, mode="round_up_to_multiple")
FAKE_HANGER_ROUNDING_ENABLED = HangerRoundingRule(enabled=True, mode="round_up_to_multiple")


# ─── color_extraction с fake tokens ──────────────────────────────────────────


class TestColorExtractionWithFakeConfig:
    """Сервис извлечения цвета работает с любыми токенами из канона."""

    def test_extract_uses_fake_tokens(self) -> None:
        assert extract_color_from_text("profile test.silver matte", FAKE_COLOR_TOKENS) == "silver"
        assert extract_color_from_text("profile testblack matte", FAKE_COLOR_TOKENS) == "black"

    def test_extract_ignores_prod_tokens_when_fake_passed(self) -> None:
        # Prod-токен "анодсеребро" не должен матчиться с fake-токенами
        assert extract_color_from_text("анодсеребро", FAKE_COLOR_TOKENS) is None

    def test_resolve_payload_color_with_fake_tokens(self) -> None:
        assert resolve_payload_color(None, "test.silver profile", FAKE_COLOR_TOKENS) == "silver"
        assert resolve_payload_color("explicit", "testblack", FAKE_COLOR_TOKENS) == "explicit"

    def test_longest_match_wins_with_fake(self) -> None:
        tokens = [
            ColorToken(token="ab", color="short"),
            ColorToken(token="abcd", color="long"),
        ]
        assert extract_color_from_text("xabcdy", tokens) == "long"


# ─── hanger_quantity с fake rule ──────────────────────────────────────────────


class TestHangerQuantityWithFakeConfig:
    """Сервис округления работает с любым правилом из канона."""

    def test_disabled_rule_returns_quantity_unchanged(self) -> None:
        result = adjust_quantity_to_hanger(
            Decimal("13"), 5, hanger_rounding=FAKE_HANGER_ROUNDING_DISABLED
        )
        assert result == Decimal("13")

    def test_enabled_rule_rounds_up(self) -> None:
        result = adjust_quantity_to_hanger(
            Decimal("13"), 5, hanger_rounding=FAKE_HANGER_ROUNDING_ENABLED
        )
        assert result == Decimal("15")

    def test_enabled_rule_already_multiple(self) -> None:
        result = adjust_quantity_to_hanger(
            Decimal("10"), 5, hanger_rounding=FAKE_HANGER_ROUNDING_ENABLED
        )
        assert result is None


# ─── plan_validation с fake messages ─────────────────────────────────────────


class TestFormatValidationErrorWithFakeConfig:
    """Сервис форматирования работает с любыми текстами из канона."""

    def test_uses_fake_messages(self) -> None:
        assert format_validation_error("custom_error", FAKE_ERROR_MESSAGES) == "Custom error text"

    def test_fallback_to_code_for_unknown(self) -> None:
        assert format_validation_error("unknown_code", FAKE_ERROR_MESSAGES) == "unknown_code"

    def test_detail_suffix_with_fake(self) -> None:
        result = format_validation_error("custom_error: SKU-1", FAKE_ERROR_MESSAGES)
        assert result == "Custom error text (SKU-1)"

    def test_prod_messages_not_used_when_fake_passed(self) -> None:
        # Prod-ключ "product_not_found" отсутствует в fake → fallback на код
        assert format_validation_error("product_not_found", FAKE_ERROR_MESSAGES) == "product_not_found"
