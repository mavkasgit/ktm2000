"""Свод эффектов force-delete: знак компенсации — из ledger (#317, DoD #110).

``_aggregate_stock_effects`` — чистая функция над строками проекции из
``_collect_footprint``. Тест кормит её фиктивными строками и сверяет ТОЧНЫЕ
числа по каждому ключу (не «не пусто»), чем и делает проверяемым пункт DoD
«итоги превью force-delete на фикстуре с компенсациями не изменились»:
колонка ``signed_quantity`` (= ``net_quantity_expr()``) подставляется туда,
где раньше стоял питоновский ``sign``, а ``sign * quantity == signed_quantity``
построчно — поэтому числа прежние.

Компенсированная строка несёт ``signed_quantity = -quantity`` (ADR-0017), и это
значение умножается на приход/расход ОБЕИХ локаций так же, как раньше
умножался ``sign`` — именно эту проводку знака фиксирует тест.

ВАЖНО, зафиксировано честно: полностью компенсированная ПАРА в этом своде
суммируется в ±2·quantity, а не в ноль. Компенсация записана с зеркальной
геометрией (``from``/``to`` перевёрнуты) И отрицательным ``signed_quantity``,
поэтому свод «снимает и переворачивает» дважды. Баланс-проекция считает иначе —
``SUM(quantity по to) − SUM(quantity по from)``, без ``reverses_id``
(``app/stock/services.py::StockProjectionManager.refresh_balance``) — и для
пары даёт ноль. Расхождение предсуществующее: #317 его не менял (числа до и
после правки требуются одинаковыми), правка семантики свода — вне скоупа
#317 и не принимается здесь молча.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services.import_batch_force_delete import _aggregate_stock_effects


def _row(*, loc_from: int | None, loc_to: int | None, signed: str) -> SimpleNamespace:
    """Строка проекции ``_collect_footprint``: несёт ``signed_quantity`` из ledger."""
    return SimpleNamespace(
        sku="SKU",
        from_location_id=loc_from,
        to_location_id=loc_to,
        from_quality_state="good",
        to_quality_state="good",
        dimensions=None,
        completed_operations=None,
        signed_quantity=Decimal(signed),
    )


def _deltas(rows) -> dict[int, str]:
    return {
        e["location_id"]: e["net_delta"]
        for e in _aggregate_stock_effects(rows, {}, [])
    }


def test_original_row_moves_material_source_to_target() -> None:
    assert _deltas([_row(loc_from=1, loc_to=2, signed="10")]) == {
        1: "-10",
        2: "10",
    }


def test_compensation_row_sign_comes_from_ledger() -> None:
    """``signed_quantity=-q`` (компенсация) даёт то же плечо, что старый ``sign``."""
    assert _deltas([_row(loc_from=2, loc_to=1, signed="-10")]) == {
        1: "-10",
        2: "10",
    }


def test_half_compensation_pair_exact_numbers() -> None:
    """Полукомпенсированная пара: ровно половина плеча оригинала (числа)."""
    assert _deltas(
        [
            _row(loc_from=1, loc_to=2, signed="10"),
            _row(loc_from=2, loc_to=1, signed="-5"),
        ]
    ) == {1: "-15", 2: "15"}


def test_full_compensation_pair_not_zero_pre_existing() -> None:
    """Полная компенсация даёт ±2·q, НЕ ноль.

    Это поведение #317 сохраняет 1:1 (было ``direction * sign * quantity``,
    стало ``direction * signed_quantity`` — то же число). Расхождение с
    баланс-проекцией (там ноль) — предсуществующее и вне скоупа #317; тест
    фиксирует факт, чтобы правка семантики была явным отдельным решением.
    """
    assert _deltas(
        [
            _row(loc_from=1, loc_to=2, signed="10"),
            _row(loc_from=2, loc_to=1, signed="-10"),
        ]
    ) == {1: "-20", 2: "20"}


def test_aggregate_no_longer_reads_reverses_id() -> None:
    """Свод берёт знак из колонки, а не пересчитывает его по ``reverses_id``.

    Строки без атрибута ``reverses_id`` обрабатываются; строка с ``reverses_id``
    но без ``signed_quantity`` — падает (нет возврата к пересчёту знака).
    """
    assert _deltas([_row(loc_from=1, loc_to=2, signed="10")]) == {1: "-10", 2: "10"}
    legacy = SimpleNamespace(
        sku="SKU",
        from_location_id=1,
        to_location_id=2,
        from_quality_state="good",
        to_quality_state="good",
        dimensions=None,
        completed_operations=None,
        reverses_id=None,
        quantity=Decimal(10),
    )
    with pytest.raises(AttributeError):
        _aggregate_stock_effects([legacy], {}, [])
