from __future__ import annotations

from app.seeds.canon.models import ColorToken

# Типизированные токены из канона (ADR-0004). Сервис не импортирует plant_policies.
from app.seeds.canon.registry import build_plant_config as _build

_DEFAULT_TOKENS: list[ColorToken] = _build().display.colors.tokens


def extract_color_from_text(
    text: str, color_tokens: list[ColorToken] | None = None
) -> str | None:
    """Extract normalized anod color token from free text (longest match wins).

    Токены читаются из канона заводской конфигурации (ADR-0004).
    """
    if not text or not text.strip():
        return None
    tokens = color_tokens if color_tokens is not None else _DEFAULT_TOKENS
    text_lower = text.lower()
    best: tuple[str, str] | None = None
    for item in tokens:
        token = item.token
        color = item.color
        if token and color and token in text_lower:
            if best is None or len(token) > len(best[0]):
                best = (token, color)
    return best[1] if best else None


def _resolve_composite_color(
    color: str, color_tokens: list[ColorToken] | None = None
) -> str:
    if "/" not in color:
        return color
    segments = [segment.strip() for segment in color.split("/") if segment.strip()]
    if not segments:
        return color
    last_segment = segments[-1]
    extracted = extract_color_from_text(last_segment, color_tokens)
    return extracted or last_segment


def resolve_payload_color(
    color: str | None,
    product_name: str | None,
    color_tokens: list[ColorToken] | None = None,
) -> str | None:
    """Resolve payload.color: explicit Excel value wins; fallback from product name."""
    if color and str(color).strip():
        color_str = str(color).strip()
        if "/" in color_str:
            return _resolve_composite_color(color_str, color_tokens)
        return color_str

    if product_name:
        return extract_color_from_text(product_name, color_tokens)

    return None