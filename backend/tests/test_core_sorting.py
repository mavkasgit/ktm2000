"""Общий контракт сортировки: core/sorting.py."""

import pytest
from fastapi import HTTPException

from app.core.sorting import SortClause, apply_sort, parse_sort, sort_items


def test_parses_multiple_clauses_in_priority_order():
    clauses = parse_sort("status:desc,product_sku:asc", default=SortClause("created_at", "desc"))
    assert [(c.field, c.order) for c in clauses] == [
        ("status", "desc"),
        ("product_sku", "asc"),
    ]


def test_empty_sort_falls_back_to_endpoint_default():
    default = SortClause("sequence", "asc")
    assert parse_sort(None, default=default) == [default]
    assert parse_sort("", default=default) == [default]
    assert parse_sort("   ", default=default) == [default]


def test_field_without_colon_is_ascending():
    clauses = parse_sort("sku", default=SortClause("created_at", "desc"))
    assert clauses == [SortClause("sku", "asc")]


def test_repeated_field_keeps_earlier_priority():
    clauses = parse_sort("sku:asc,status:desc,sku:desc", default=SortClause("created_at", "desc"))
    assert [(c.field, c.order) for c in clauses] == [("sku", "asc"), ("status", "desc")]


def test_invalid_order_rejected_with_400():
    with pytest.raises(HTTPException) as exc:
        parse_sort("sku:sideways", default=SortClause("created_at", "desc"))
    assert exc.value.status_code == 400


def test_empty_field_rejected_with_400():
    with pytest.raises(HTTPException) as exc:
        parse_sort(":asc", default=SortClause("created_at", "desc"))
    assert exc.value.status_code == 400


def test_apply_sort_rejects_field_outside_column_table():
    class FakeStmt:
        def order_by(self, *keys):
            return keys

    with pytest.raises(HTTPException) as exc:
        apply_sort(FakeStmt(), [SortClause("unknown", "asc")], {"sku": "COL"}, tiebreaker="ID")
    assert exc.value.status_code == 400
    assert "unknown" in exc.value.detail


def test_apply_sort_puts_tiebreaker_last_regardless_of_direction():
    rendered: list[str] = []

    class Expr:
        def __init__(self, name, direction, nulls=False):
            self.name = name
            self.direction = direction
            self.nulls = nulls

        def __str__(self):
            return f"{self.name} {self.direction}{' nulls_last' if self.nulls else ''}"

        def nulls_last(self):
            self.nulls = True
            return self

    class Column:
        def __init__(self, name):
            self.name = name

        def asc(self):
            return Expr(self.name, "asc")

        def desc(self):
            return Expr(self.name, "desc")

    class FakeNullsLast(Column):
        def asc(self):
            return Expr(self.name, "asc", nulls=True)

        def desc(self):
            return Expr(self.name, "desc", nulls=True)

    class FakeStmt:
        def order_by(self, *keys):
            rendered.extend(str(key) for key in keys)
            return keys

    apply_sort(
        FakeStmt(),
        [SortClause("status", "desc"), SortClause("sku", "asc")],
        {"status": Column("status"), "sku": FakeNullsLast("sku")},
        tiebreaker=Column("id"),
        nulls_last=["sku"],
    )
    assert rendered == ["status desc", "sku asc nulls_last", "id asc"]


def test_apply_sort_resolves_callable_columns():
    rendered: list[str] = []

    class FakeStmt:
        def order_by(self, *keys):
            rendered.extend(keys)
            return keys

    class Tiebreaker:
        def asc(self):
            return "id asc"

    class Column:
        def asc(self):
            return "subq asc"

    apply_sort(
        FakeStmt(),
        [SortClause("length_mm", "asc")],
        {"length_mm": lambda: Column()},
        tiebreaker=Tiebreaker(),
    )
    assert rendered == ["subq asc", "id asc"]


def test_sort_items_orders_by_later_clause_then_earlier():
    rows = [
        {"status": "b", "sku": "2", "n": 2},
        {"status": "a", "sku": "2", "n": 1},
        {"status": "b", "sku": "1", "n": 3},
        {"status": "a", "sku": "1", "n": 0},
    ]
    ordered = sort_items(
        rows,
        [SortClause("sku", "asc"), SortClause("status", "asc")],
        {"sku": lambda r: r["sku"], "status": lambda r: r["status"]},
    )
    assert [(r["sku"], r["status"]) for r in ordered] == [
        ("1", "a"),
        ("1", "b"),
        ("2", "a"),
        ("2", "b"),
    ]


def test_sort_items_keeps_nulls_last_in_both_directions():
    rows = [{"v": 3}, {"v": None}, {"v": 1}]
    ascending = sort_items(rows, [SortClause("v", "asc")], {"v": lambda r: r["v"]}, nulls_last=["v"])
    assert [r["v"] for r in ascending] == [1, 3, None]

    descending = sort_items(rows, [SortClause("v", "desc")], {"v": lambda r: r["v"]}, nulls_last=["v"])
    assert [r["v"] for r in descending] == [3, 1, None]


def test_sort_items_rejects_field_outside_key_table():
    with pytest.raises(HTTPException) as exc:
        sort_items([{"a": 1}], [SortClause("nope", "asc")], {"a": lambda r: r["a"]})
    assert exc.value.status_code == 400


def test_sort_items_tiebreaker_makes_equal_rows_stable():
    # Сортировка по n desc: сначала n=1 (id 1 и 3), затем n=0 (id 2).
    # Tiebreaker — младший приоритет, он раскладывает равные n по id:
    # при n=1 идёт 1 раньше 3, и результат не зависит от исходного порядка.
    rows = [{"n": 1, "id": 3}, {"n": 1, "id": 1}, {"n": 0, "id": 2}]
    ordered = sort_items(
        rows,
        [SortClause("n", "desc")],
        {"n": lambda r: r["n"]},
        tiebreaker=lambda r: r["id"],
    )
    assert [r["id"] for r in ordered] == [1, 3, 2]

    # Тот же набор во входном порядке, обратном предыдущему, — тот же результат.
    shuffled = [{"n": 0, "id": 2}, {"n": 1, "id": 1}, {"n": 1, "id": 3}]
    assert [
        r["id"]
        for r in sort_items(
            shuffled,
            [SortClause("n", "desc")],
            {"n": lambda r: r["n"]},
            tiebreaker=lambda r: r["id"],
        )
    ] == [1, 3, 2]
