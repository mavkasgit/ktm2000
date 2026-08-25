"""Юнит-тесты сборки строк по выходам трансформирующей задачи (тикет #125).

Чистый тест без БД: ``build_output_rows`` — синхронная чистая функция;
async-обёртки (``get_used_by_group`` / ``build_task_output_rows``) — тонкий
wiring, закрытый существующими API-тестами.

Фикстура из спеки: трансформация 2,7 м → 0,9 м + 1,8 м; частичная передача
и финальный выпуск. Ожидание (CONTEXT.md «Сдача»): строка на каждый выход.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.dimensions import canonicalize_dimensions
from app.services.shopfloor.output_rows import build_output_rows
from app.stock.services import _dimensions_hash_key


def _key(dims: dict | None) -> str | None:
    """Ключ группировки габарита — тот же, что в ledger-агрегатах."""
    return _dimensions_hash_key(canonicalize_dimensions(dims))


# Спецификация: 2,7 м входа → 0,9 м + 1,8 м.
OUTPUTS = [
    {"row_number": 1, "dimensions": {"length_mm": 900}, "quantity": "0.9"},
    {"row_number": 2, "dimensions": {"length_mm": 1800}, "quantity": "1.8"},
]

K09 = _key({"length_mm": 900})
K18 = _key({"length_mm": 1800})


def test_row_per_output_with_partial_transfer():
    """Полностью произведено; частично передан только размер 0,9.

    Строка на каждый выход спецификации, remaining = produced − used,
    без отрицательных остатков и без пропущенных строк.
    """
    rows = build_output_rows(
        OUTPUTS,
        {K09: Decimal("0.9"), K18: Decimal("1.8")},
        {K09: Decimal("0.45")},  # частичная передача размера 0,9
    )

    assert len(rows) == 2
    first, second = rows
    assert first.row_number == 1
    assert first.dimensions == {"length_mm": 900}
    assert first.quantity == Decimal("0.9")
    assert first.produced_quantity == Decimal("0.9")
    assert first.used_quantity == Decimal("0.45")
    assert first.remaining_quantity == Decimal("0.45")
    assert second.row_number == 2
    assert second.dimensions == {"length_mm": 1800}
    assert second.quantity == Decimal("1.8")
    assert second.produced_quantity == Decimal("1.8")
    assert second.used_quantity == Decimal("0")
    assert second.remaining_quantity == Decimal("1.8")


def test_final_release_used_per_dimension():
    """Финальный выпуск по размеру 1,8 закрывает только его остаток."""
    rows = build_output_rows(
        OUTPUTS,
        {K09: Decimal("0.9"), K18: Decimal("1.8")},
        {K18: Decimal("1.8")},
    )

    assert [r.remaining_quantity for r in rows] == [
        Decimal("0.9"),
        Decimal("0"),
    ]


def test_produced_and_used_fill_sequentially_within_same_dimensions():
    """Две строки одного размера не делят бюджет дважды (тикет #91).

    Произведено 1,2 м размера 0,9 при плане 0,9 + 0,9: первая строка
    заполняется первой, второй достаётся остаток. Передано 1,0 м —
    распределяется так же последовательно.
    """
    outputs = [
        {"row_number": 1, "dimensions": {"length_mm": 900}, "quantity": "0.9"},
        {"row_number": 2, "dimensions": {"length_mm": 900}, "quantity": "0.9"},
    ]
    rows = build_output_rows(
        outputs,
        {K09: Decimal("1.2")},
        {K09: Decimal("1.0")},
    )

    assert [r.produced_quantity for r in rows] == [
        Decimal("0.9"),
        Decimal("0.3"),
    ]
    assert [r.used_quantity for r in rows] == [
        Decimal("0.9"),
        Decimal("0.1"),
    ]
    assert [r.remaining_quantity for r in rows] == [
        Decimal("0"),
        Decimal("0.2"),
    ]


def test_produced_capped_by_plan_row_quantity():
    """Произведённое больше плана строки не раздувает produced."""
    rows = build_output_rows(
        OUTPUTS[:1],
        {K09: Decimal("5.0")},
        {},
    )
    assert rows[0].produced_quantity == Decimal("0.9")


def test_remaining_never_negative_when_used_exceeds_produced():
    """Передано/выпущено больше произведённого — остаток клампится в 0."""
    rows = build_output_rows(OUTPUTS, {K09: Decimal("0.9")}, {K09: Decimal("1.5")})
    assert rows[0].remaining_quantity == Decimal("0")


def test_output_without_quantity_is_zero_row():
    """Строка выхода без quantity даёт нулевую строку, а не падение."""
    outputs = [{"row_number": 3, "dimensions": {"length_mm": 600}, "quantity": None}]
    rows = build_output_rows(outputs, {}, {})
    assert len(rows) == 1
    row = rows[0]
    assert row.quantity == Decimal("0")
    assert row.produced_quantity == Decimal("0")
    assert row.used_quantity == Decimal("0")
    assert row.remaining_quantity == Decimal("0")
