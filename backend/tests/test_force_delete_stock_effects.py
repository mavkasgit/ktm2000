"""Свод эффектов force-delete: знак — из геометрии проводки (#329, DoD #110).

``_aggregate_stock_effects`` — чистая функция над строками проекции из
``_collect_footprint``. Тест кормит её фиктивными строками и сверяет ТОЧНЫЕ
числа по каждому ключу (не «не пусто»).

Свод считает по геометрии: вход (``to_location_id``) плюсует ``quantity``,
выход (``from_location_id``) вычитает — та же арифметика, что у
материализованной баланс-проекции (``SUM(quantity)`` по обеим сторонам,
``app/stock/services.py::StockProjectionManager._recompute_balance``). Строка
несёт ``quantity``; отдельной колонки знака нет, признак отмены свод не
читает вообще — поэтому ключ строки с зеркальной геометрией даёт
противоположное плечо и гасит исходное.

Полностью компенсированная ПАРА даёт пустой свод: компенсация записана с
зеркальной геометрией (``from``/``to`` перевёрнуты), плечо переворачивается
один раз — ровно как в баланс-проекции. Раньше свод применял ledger-знак к
уже перевёрнутой геометрии и получал ±2·quantity вместо нуля (#329); числа
ниже — зелёное ожидание «ноль/пусто».
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services.import_batch_force_delete import _aggregate_stock_effects


def _row(
    *,
    loc_from: int | None,
    loc_to: int | None,
    quantity: str,
    reverses_id: int | None = None,
) -> SimpleNamespace:
    """Строка проекции ``_collect_footprint``: несёт ``quantity`` ledger.

    ``reverses_id`` по умолчанию не передаётся — свод обязан работать без
    него; переданный значение игнорирует (знак даёт только геометрия).
    """
    row = SimpleNamespace(
        sku="SKU",
        from_location_id=loc_from,
        to_location_id=loc_to,
        from_quality_state="good",
        to_quality_state="good",
        dimensions=None,
        completed_operations=None,
        quantity=Decimal(quantity),
    )
    if reverses_id is not None:
        row.reverses_id = reverses_id
    return row


def _deltas(rows) -> dict[int, str]:
    return {
        e["location_id"]: e["net_delta"]
        for e in _aggregate_stock_effects(rows, {}, [])
    }


def test_original_row_moves_material_source_to_target() -> None:
    assert _deltas([_row(loc_from=1, loc_to=2, quantity="10")]) == {
        1: "-10",
        2: "10",
    }


def test_compensation_row_mirror_geometry_flips_the_leg() -> None:
    """Компенсация (зеркальная геометрия) даёт противоположное плечо."""
    assert _deltas([_row(loc_from=2, loc_to=1, quantity="10")]) == {
        1: "10",
        2: "-10",
    }


def test_full_compensation_pair_is_empty() -> None:
    """Полностью компенсированная пара гасится в ноль, а не даёт ±2·q.

    Свод совпадает с баланс-проекцией: там пара тоже даёт ноль, потому что
    компенсация записана зеркальной геометрией (#329).
    """
    rows = [
        _row(loc_from=1, loc_to=2, quantity="10"),
        _row(loc_from=2, loc_to=1, quantity="10"),
    ]
    assert _aggregate_stock_effects(rows, {}, []) == []
    assert _deltas(rows) == {}


def test_half_compensation_pair_exact_numbers() -> None:
    """Полукомпенсированная пара: ровно половина плеча оригинала (числа)."""
    assert _deltas(
        [
            _row(loc_from=1, loc_to=2, quantity="10"),
            _row(loc_from=2, loc_to=1, quantity="5"),
        ]
    ) == {1: "-5", 2: "5"}


def test_aggregate_no_longer_reads_reverses_id() -> None:
    """Свод читает ``quantity`` и не читает признак отмены вообще.

    Строки несут ``quantity`` (без колонки знака) и обрабатываются; строка с
    переданным ``reverses_id`` даёт тот же результат, что и без него — знак
    определяется только геометрией. Обратная проба: строка с колонкой знака,
    но без ``quantity``, падает — свод не имеет запасного источника знака.
    """
    plain = _row(loc_from=1, loc_to=2, quantity="10")
    assert _deltas([plain]) == {1: "-10", 2: "10"}
    assert _deltas([_row(loc_from=1, loc_to=2, quantity="10", reverses_id=777)]) == {
        1: "-10",
        2: "10",
    }

    signed_only = SimpleNamespace(
        sku="SKU",
        from_location_id=1,
        to_location_id=2,
        from_quality_state="good",
        to_quality_state="good",
        dimensions=None,
        completed_operations=None,
        signed_quantity=Decimal(10),
    )
    with pytest.raises(AttributeError):
        _aggregate_stock_effects([signed_only], {}, [])
