from __future__ import annotations

_COLOR_TOKENS: list[tuple[str, str]] = [
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


def extract_color_from_text(text: str) -> str | None:
    """Extract normalized anod color token from free text (longest match wins)."""
    if not text or not text.strip():
        return None
    text_lower = text.lower()
    best: tuple[str, str] | None = None
    for token, color in _COLOR_TOKENS:
        if token in text_lower:
            if best is None or len(token) > len(best[0]):
                best = (token, color)
    return best[1] if best else None


def _resolve_composite_color(color: str) -> str:
    if "/" not in color:
        return color
    segments = [segment.strip() for segment in color.split("/") if segment.strip()]
    if not segments:
        return color
    last_segment = segments[-1]
    extracted = extract_color_from_text(last_segment)
    return extracted or last_segment


def resolve_payload_color(color: str | None, product_name: str | None) -> str | None:
    """Resolve payload.color: explicit Excel value wins; fallback from product name."""
    if color and str(color).strip():
        color_str = str(color).strip()
        if "/" in color_str:
            return _resolve_composite_color(color_str)
        return color_str

    if product_name:
        return extract_color_from_text(product_name)

    return None