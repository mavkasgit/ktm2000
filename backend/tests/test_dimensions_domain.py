"""Чистые unit-тесты доменного модуля габаритов (app.domain.dimensions).

Без БД, без async-фикстур приложения — только чистые функции.
Термины и контракт: CONTEXT.md → «Габариты», ADR-0001.
"""
from __future__ import annotations

import pytest

from app.domain.dimensions import (
    LENGTH_MM,
    DimensionsValidationError,
    canonicalize_dimensions,
    dimensions_equal,
    format_dimensions,
    format_operation_summary,
    parse_length_m_to_mm,
)


# ---------------------------------------------------------------------------
# canonicalize_dimensions
# ---------------------------------------------------------------------------


class TestCanonicalizeDimensions:
    def test_none_stays_none(self):
        assert canonicalize_dimensions(None) is None

    def test_empty_dict_becomes_none(self):
        assert canonicalize_dimensions({}) is None

    def test_float_integral_value_normalized_to_int(self):
        result = canonicalize_dimensions({"length_mm": 2700.0})
        assert result == {"length_mm": 2700}
        assert isinstance(result["length_mm"], int)

    def test_non_integral_float_preserved(self):
        result = canonicalize_dimensions({"length_mm": 2700.5})
        assert result == {"length_mm": 2700.5}
        assert isinstance(result["length_mm"], float)

    def test_key_order_is_stable(self):
        a = canonicalize_dimensions({"width_mm": 1200, "height_mm": 2400})
        b = canonicalize_dimensions({"height_mm": 2400, "width_mm": 1200})
        assert a == b
        assert list(a.keys()) == list(b.keys()) == ["height_mm", "width_mm"]

    def test_extra_keys_preserved(self):
        result = canonicalize_dimensions({"length_mm": 2700, "grade": "A"})
        assert result == {"grade": "A", "length_mm": 2700}

    def test_input_dict_not_mutated(self):
        raw = {"width_mm": 1200.0, "height_mm": 2400}
        canonicalize_dimensions(raw)
        assert raw == {"width_mm": 1200.0, "height_mm": 2400}

    @pytest.mark.parametrize("value", [0, 0.0, -1, -2700, -0.5])
    def test_zero_and_negative_values_rejected(self, value):
        with pytest.raises(DimensionsValidationError):
            canonicalize_dimensions({"length_mm": value})

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_rejected(self, value):
        with pytest.raises(DimensionsValidationError):
            canonicalize_dimensions({"length_mm": value})

    @pytest.mark.parametrize("value", [True, False, None])
    def test_bool_and_none_values_rejected(self, value):
        with pytest.raises(DimensionsValidationError):
            canonicalize_dimensions({"length_mm": value})

    @pytest.mark.parametrize("key", [1, None, ("length_mm",), ""])
    def test_non_string_or_empty_keys_rejected(self, key):
        with pytest.raises(DimensionsValidationError):
            canonicalize_dimensions({key: 2700})

    @pytest.mark.parametrize("raw", ["length_mm", 2700, [("length_mm", 2700)]])
    def test_non_mapping_input_rejected(self, raw):
        with pytest.raises(DimensionsValidationError):
            canonicalize_dimensions(raw)


# ---------------------------------------------------------------------------
# parse_length_m_to_mm
# ---------------------------------------------------------------------------


class TestParseLengthMToMm:
    @pytest.mark.parametrize(
        ("raw", "expected_mm"),
        [
            ("2,7", 2700),
            ("2.75", 2750),
            ("0,9", 900),
            ("1", 1000),
            ("1.350", 1350),
            (" 2,7 ", 2700),
            (" 1 350 ", 1_350_000),  # пробелы-разделители тысяч
            ("1\xa0350", 1_350_000),  # неразрывный пробел из Excel
            (2.7, 2700),
            (2.75, 2750),
            (3, 3000),
        ],
    )
    def test_valid_values(self, raw, expected_mm):
        result = parse_length_m_to_mm(raw)
        assert result == expected_mm
        assert isinstance(result, int)

    @pytest.mark.parametrize("raw", ["abc", "", "   ", "2,7,5", "1.2.3", "2,7м"])
    def test_garbage_strings_raise_not_silent_none(self, raw):
        with pytest.raises(DimensionsValidationError):
            parse_length_m_to_mm(raw)

    @pytest.mark.parametrize("raw", ["0", "0,0", 0, 0.0, "-2,7", -1, -0.5])
    def test_zero_and_negative_raise(self, raw):
        with pytest.raises(DimensionsValidationError):
            parse_length_m_to_mm(raw)

    @pytest.mark.parametrize("raw", [None, True, False, ["2,7"], {"m": 2.7}])
    def test_unsupported_types_raise(self, raw):
        with pytest.raises(DimensionsValidationError):
            parse_length_m_to_mm(raw)

    def test_float_artifacts_rounded(self):
        # 2.7 * 1000 в float = 2700.0000000000002 — должно стать ровно 2700
        assert parse_length_m_to_mm(0.1 + 0.2) == 300


# ---------------------------------------------------------------------------
# dimensions_equal
# ---------------------------------------------------------------------------


class TestDimensionsEqual:
    def test_equal_via_canonical_form(self):
        assert dimensions_equal({"length_mm": 2700.0}, {"length_mm": 2700})

    def test_key_order_does_not_matter(self):
        assert dimensions_equal(
            {"width_mm": 1200, "height_mm": 2400},
            {"height_mm": 2400, "width_mm": 1200},
        )

    def test_none_equals_empty_dict(self):
        assert dimensions_equal(None, {})
        assert dimensions_equal(None, None)

    def test_none_not_equal_to_dimensioned(self):
        assert not dimensions_equal(None, {"length_mm": 2700})

    def test_different_values_not_equal(self):
        assert not dimensions_equal({"length_mm": 2700}, {"length_mm": 3000})

    def test_extra_key_makes_not_equal(self):
        assert not dimensions_equal(
            {"length_mm": 2700},
            {"length_mm": 2700, "grade": "A"},
        )


# ---------------------------------------------------------------------------
# format_dimensions
# ---------------------------------------------------------------------------


class TestFormatDimensions:
    def test_none_is_dash(self):
        assert format_dimensions(None) == "—"

    def test_empty_dict_is_dash(self):
        assert format_dimensions({}) == "—"

    @pytest.mark.parametrize(
        ("mm", "expected"),
        [
            (2700, "2,7 м"),
            (2750, "2,75 м"),
            (900, "0,9 м"),
            (1000, "1 м"),
            (1350, "1,35 м"),
        ],
    )
    def test_length_formatted_in_meters(self, mm, expected):
        assert format_dimensions({LENGTH_MM: mm}) == expected

    def test_float_length_canonicalized_before_formatting(self):
        assert format_dimensions({LENGTH_MM: 2700.0}) == "2,7 м"

    def test_other_keys_fallback_in_canonical_order(self):
        result = format_dimensions({"width_mm": 1200, "height_mm": 2400})
        assert result == "height_mm: 2400, width_mm: 1200"

    def test_invalid_dimensions_raise(self):
        with pytest.raises(DimensionsValidationError):
            format_dimensions({LENGTH_MM: 0})


# ---------------------------------------------------------------------------
# format_operation_summary
# ---------------------------------------------------------------------------


class TestFormatOperationSummary:
    def test_no_outputs_is_none(self):
        assert format_operation_summary(150, {"length_mm": 2700}, []) is None

    def test_fully_dimensionless_is_none(self):
        assert format_operation_summary(None, None, [{"quantity": "150"}]) is None

    def test_transform_shows_input_and_outputs(self):
        result = format_operation_summary(
            150,
            {"length_mm": 2700},
            [
                {"quantity": "150", "dimensions": {"length_mm": 900}},
                {"quantity": "150", "dimensions": {"length_mm": 1800}},
            ],
        )
        assert result == "150 шт × 2,7 м → 150 × 0,9 м + 150 × 1,8 м"

    def test_same_length_is_none(self):
        assert format_operation_summary(
            150,
            {"length_mm": 2700},
            [{"quantity": "150", "dimensions": {"length_mm": 2700}}],
        ) is None

    def test_same_length_multiple_outputs_is_none(self):
        assert format_operation_summary(
            300,
            {"length_mm": 2700},
            [
                {"quantity": "150", "dimensions": {"length_mm": 2700}},
                {"quantity": "150", "dimensions": {"length_mm": 2700}},
            ],
        ) is None

    def test_float_length_normalized_still_equal(self):
        assert format_operation_summary(
            150,
            {"length_mm": 2700.0},
            [{"quantity": "150", "dimensions": {"length_mm": 2700}}],
        ) is None

    def test_dimensionless_input_to_dimensioned_output_shows(self):
        result = format_operation_summary(
            150,
            None,
            [{"quantity": "150", "dimensions": {"length_mm": 2700}}],
        )
        assert result == "150 шт → 150 × 2,7 м"
