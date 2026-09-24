"""Публичные контракты расчёта подвеса по сырьевой длине (ADR-0028)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import (
    HANGER_MODE_AUTO,
    Product,
    ProductLength,
    ProductPair,
    ProductType,
)
from app.services.plan_position_hanger import resolve_position_hanger
from app.services.product_pair_resolver import (
    PairLengthCandidate,
    ResolvedPair,
    pair_length_candidates,
    resolve_pair_n,
)


def _single_product(
    sku: str,
    *,
    length_mm: float,
    raw_length_mm: float | None,
    perimeter_mm: float = 50.0,
    mount_width_mm: float = 1.0,
) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.component,
        unit="pcs",
        perimeter_mm=perimeter_mm,
        mount_width_mm=mount_width_mm,
        hanger_mode=HANGER_MODE_AUTO,
    )
    product.lengths.append(
        ProductLength(
            length_mm=length_mm,
            raw_length_mm=raw_length_mm,
            is_primary=True,
        )
    )
    return product


async def _pair(
    session: AsyncSession,
    *,
    raw_a_mm: float | None,
    raw_b_mm: float | None,
    manual_n: int | None = None,
    length_mm: float = 2700.0,
) -> ResolvedPair:
    product_a = _single_product(
        "RAW-PAIR-A",
        length_mm=length_mm,
        raw_length_mm=raw_a_mm,
        perimeter_mm=25.0,
    )
    product_b = _single_product(
        "RAW-PAIR-B",
        length_mm=length_mm,
        raw_length_mm=raw_b_mm,
        perimeter_mm=25.0,
    )
    session.add_all([product_a, product_b])
    await session.flush()

    pair = ProductPair(
        product_a_id=product_a.id,
        product_b_id=product_b.id,
        quantity_per_hanger=(
            {str(int(length_mm)): {"auto": None, "manual": manual_n}}
            if manual_n is not None
            else {}
        ),
    )
    session.add(pair)
    await session.flush()
    return ResolvedPair(pair=pair, product_a=product_a, product_b=product_b)


def test_single_auto_formula_uses_explicit_raw_length() -> None:
    product = _single_product(
        "RAW-SINGLE-EXPLICIT",
        length_mm=2700.0,
        raw_length_mm=2750.0,
    )

    resolved = resolve_position_hanger(
        product,
        length_mm=2700.0,
        payload_quantity_per_hanger=None,
    )

    # 13 / (50 * 2750 / 1_000_000) = 94.54 → 94; ограничение по размеру 138.
    assert resolved.quantity_per_hanger == 94
    assert resolved.source == "auto"
    assert resolved.calc_error is False


def test_single_auto_with_null_raw_falls_back_to_normal_length() -> None:
    product = _single_product(
        "RAW-SINGLE-NULL",
        length_mm=2700.0,
        raw_length_mm=None,
    )

    resolved = resolve_position_hanger(
        product,
        length_mm=2700.0,
        payload_quantity_per_hanger=None,
    )

    # 13 / (50 * 2700 / 1_000_000) = 96.29 → 96.
    assert resolved.quantity_per_hanger == 96
    assert resolved.source == "auto"
    assert resolved.calc_error is False


@pytest.mark.asyncio
async def test_pair_auto_uses_equal_explicit_raw_lengths(session: AsyncSession) -> None:
    resolved_pair = await _pair(session, raw_a_mm=2750.0, raw_b_mm=2750.0)
    candidates = await pair_length_candidates(session, resolved_pair)

    resolved = await resolve_pair_n(
        session,
        resolved_pair,
        length_mm=2700.0,
        length_candidates=candidates,
    )

    assert candidates == [
        PairLengthCandidate(
            length_mm=2700.0,
            raw_length_a_mm=2750.0,
            raw_length_b_mm=2750.0,
        )
    ]
    # by_area=94, но by_size=floor(2900 / (1 + 1 + 40))=69 ограничивает N.
    assert resolved.quantity_per_hanger == 69
    assert resolved.source == "auto"
    assert resolved.calc_error is False


@pytest.mark.asyncio
async def test_pair_auto_rejects_mismatched_effective_raw_lengths(
    session: AsyncSession,
) -> None:
    resolved_pair = await _pair(session, raw_a_mm=2750.0, raw_b_mm=None)
    candidates = await pair_length_candidates(session, resolved_pair)

    resolved = await resolve_pair_n(
        session,
        resolved_pair,
        length_mm=2700.0,
        length_candidates=candidates,
    )

    assert candidates == [
        PairLengthCandidate(
            length_mm=2700.0,
            raw_length_a_mm=2750.0,
            raw_length_b_mm=2700.0,
        )
    ]
    assert resolved.quantity_per_hanger is None
    assert resolved.source is None
    assert resolved.calc_error is True


@pytest.mark.asyncio
async def test_pair_manual_n_succeeds_despite_mismatched_raw_lengths(
    session: AsyncSession,
) -> None:
    resolved_pair = await _pair(
        session,
        raw_a_mm=2750.0,
        raw_b_mm=None,
        manual_n=17,
    )

    resolved = await resolve_pair_n(session, resolved_pair, length_mm=2700.0)

    assert resolved.quantity_per_hanger == 17
    assert resolved.source == "manual"
    assert resolved.calc_error is False


def test_single_raw_length_keeps_existing_by_size_limit() -> None:
    explicit_raw = _single_product(
        "RAW-SINGLE-SIZE-RAW",
        length_mm=2700.0,
        raw_length_mm=4000.0,
        perimeter_mm=10.0,
        mount_width_mm=100.0,
    )
    null_raw = _single_product(
        "RAW-SINGLE-SIZE-NULL",
        length_mm=2700.0,
        raw_length_mm=None,
        perimeter_mm=10.0,
        mount_width_mm=100.0,
    )

    raw_result = resolve_position_hanger(
        explicit_raw,
        length_mm=2700.0,
        payload_quantity_per_hanger=None,
    )
    null_result = resolve_position_hanger(
        null_raw,
        length_mm=2700.0,
        payload_quantity_per_hanger=None,
    )

    # floor(1450 / (100 + 20)) * 2 = 24 остаётся ограничением при обоих raw.
    assert raw_result.quantity_per_hanger == 24
    assert null_result.quantity_per_hanger == 24
    assert raw_result.source == "auto"
    assert null_result.source == "auto"
