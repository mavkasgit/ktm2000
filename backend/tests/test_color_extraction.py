"""Unit tests for anod color extraction from product names."""

from __future__ import annotations

import pytest

from app.services.color_extraction import extract_color_from_text, resolve_payload_color
from app.services.route_builder import _build_route_name_from_template
from app.models.route import RouteRuleProfile


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("РП-АКТ-03 2,7 м анодтитан матов", "титан"),
        ("РП-АКТ-03 2,7 м анодчерный матов", "черный"),
        ("РП-АКТ-03 2,7 м анодчёрный матов", "черный"),
        ("Стык 38 мм. 2,7 анод.серебро, матовый", "серебро"),
        ("Профиль анодшампань глянец", "шампань"),
        ("Профиль анодзолото", "золото"),
        ("Профиль анодбронза", "бронза"),
        ("Профиль анодмедь матовый", "медь"),
        ("Профиль анодмед матовый", "медь"),
        ("Профиль анодсеребро", "серебро"),
        ("Без цветового токена", None),
    ],
)
def test_extract_color_from_text_tokens(text: str, expected: str | None) -> None:
    assert extract_color_from_text(text) == expected


def test_extract_color_from_text_longest_token_priority() -> None:
    assert extract_color_from_text("анодмедь профиль") == "медь"
    assert extract_color_from_text("анодмед профиль") == "медь"


def test_resolve_payload_color_keeps_explicit_excel_color() -> None:
    assert resolve_payload_color("серебро", "… анодтитан …") == "серебро"


def test_resolve_payload_color_fallback_from_product_name() -> None:
    assert resolve_payload_color(None, "… анодшампань …") == "шампань"


def test_resolve_payload_color_composite_takes_last_segment() -> None:
    assert resolve_payload_color("анодсеребро/анодтитан/анодчерный", None) == "черный"


def test_resolve_payload_color_composite_last_segment_extracted() -> None:
    assert resolve_payload_color("серебро/анодтитан", None) == "титан"


def test_dynamic_route_name_for_anodtitan_contains_titan() -> None:
    profile = RouteRuleProfile(
        code="packaging_map_rp",
        name="Упаковочная карта РП",
        route_name_pattern="{output_kind} - {press_op} - {drill_op} - {shot_op} - {color} - {pack_op}",
    )
    resolved_ops = {
        ("PRESSING", "PRESS"): "PRESS_WINDOW",
        ("ANODIZING", "ANOD"): "ANOD_08",
        ("ANODIZING", "PACK"): "PACK_STRETCH",
    }
    included_sections = [
        "RAW_STOCK",
        "PRESSING",
        "SHOT_BLAST",
        "ANODIZING",
        "WIP_STOCK",
        "SAWING",
        "PACKING",
        "FINISHED_STOCK",
    ]

    route_name = _build_route_name_from_template(
        profile,
        included_sections,
        set(),
        resolved_ops,
        {"output_kind": "ГП"},
    )

    assert "Титан" in route_name
    assert "Медь" not in route_name
    assert "Серебро" not in route_name