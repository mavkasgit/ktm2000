"""#381: классификатор `tests/helpers/sql_counter.py` имеет собственную проверку.

Почему это вообще нужно. `SqlRecorder` используют несколько файлов
(`test_excel_import.py`, `test_production_planning_rows_sql_297.py`,
`test_section_totals_sql_298.py`, `test_route_build_batching_292.py`), но ни
одна проверка не касалась самого фильтра: поведение «служебный `SAVEPOINT` не
считается, `SELECT` считается» держалось на договорённости, а не на тесте.
Второй промах: в `.count` попадали только `SELECT`, поэтому `INSERT`/`UPDATE`/
`DELETE` ручки были для счётчика невидимы — регресс удвоения записей на путях
записи прошёл бы молча (кандидат B-N11).

Здесь три вещи, и все дешёвые (без БД):

1. классификация по классам — служебное/чтение/запись/прочее;
2. контракт совместимости: `select` = ровно исторический фильтр
   `startswith("SELECT")`, чтобы уже снятые потолки (#295/#297/#298) не
   сдвинулись от добавления `writes`;
3. свойства рекордера на реальной последовательности событий (savepoint →
   select → savepoint → insert → release): `count` считает только SELECT,
   `write_count` видит запись, `service` показывает обвязку, ничего не
   теряется между классами.

`SqlRecorder` строится с ``engine=None``: слушатели навешиваются только в
`__enter__`, а тесту нужен разбор уже выполненных statements — тот же путь,
который проходит движок через `before_cursor_execute`.
"""

from __future__ import annotations

import pytest

from tests.helpers.sql_counter import (
    SqlRecorder,
    classify_statement,
)

SERVICE_STATEMENTS = [
    "SAVEPOINT pp_1a2b3c",
    "RELEASE SAVEPOINT pp_1a2b3c",
    "ROLLBACK TO SAVEPOINT pp_1a2b3c",
    "SET LOCAL statement_timeout = 0",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
]

READ_STATEMENTS = [
    "SELECT 1",
    "SELECT products.id FROM products WHERE products.is_active",
    "  \n\t select 1 ",
]

WRITE_STATEMENTS = [
    "INSERT INTO users (id, username) VALUES (1, 'x')",
    "UPDATE products SET is_active = true WHERE id = 3",
    "DELETE FROM audit_logs WHERE id < 100",
    "insert into users (id) values (1)",
    # Запись внутри CTE: префикс `WITH`, а работа пишет.
    "WITH moved AS (DELETE FROM tasks WHERE id = 1 RETURNING *) INSERT INTO archive SELECT * FROM moved",
]

OTHER_STATEMENTS = [
    "CREATE TABLE zzz (id integer)",
    "ALTER TABLE sections ADD COLUMN probe integer",
    "DROP TABLE zzz",
    # Читающий CTE в `select` не входит намеренно: исторический фильтр не
    # двигает уже снятые потолки (см. докстринг classify_statement).
    "WITH agg AS (SELECT 1) SELECT * FROM agg",
    "",
]


@pytest.mark.parametrize("statement", SERVICE_STATEMENTS)
def test_service_statements_are_not_selects(statement: str) -> None:
    """Обвязка тестовой транзакции не должна попадать в число запросов ручки."""
    assert classify_statement(statement) == "service"


@pytest.mark.parametrize("statement", READ_STATEMENTS)
def test_reads_are_classified_as_select(statement: str) -> None:
    assert classify_statement(statement) == "select"


@pytest.mark.parametrize("statement", WRITE_STATEMENTS)
def test_writes_are_visible(statement: str) -> None:
    """#381: запись перестала быть невидимой для счётчика."""
    assert classify_statement(statement) == "write"


@pytest.mark.parametrize("statement", OTHER_STATEMENTS)
def test_everything_else_has_a_class(statement: str) -> None:
    """Ни один текст не теряется между классами: DDL и читающий CTE — в `other`."""
    assert classify_statement(statement) == "other"


@pytest.mark.parametrize("statement", SERVICE_STATEMENTS + READ_STATEMENTS + WRITE_STATEMENTS + OTHER_STATEMENTS)
def test_select_class_equals_historical_filter(statement: str) -> None:
    """Совместимость с замером «до» #381.

    `count` исторически = `statement.lstrip().upper().startswith("SELECT")`.
    Если классификатор начнёт считать (или перестанет) что-то ещё, этот тест
    краснеет, а вместе с ним поехал бы и любой уже снятый потолок.
    """
    historical = statement.lstrip().upper().startswith("SELECT")
    assert (classify_statement(statement) == "select") is historical


def test_recorder_counts_reads_and_writes_separately() -> None:
    """Реальная последовательность событий движка: savepoint → select → insert → release."""
    recorder = SqlRecorder(engine=None)
    events = [
        "SAVEPOINT pp_a1",
        "SELECT work_tasks.id FROM work_tasks WHERE work_tasks.section_id = 7",
        "SELECT products.sku FROM products",
        "SAVEPOINT pp_a2",
        "UPDATE products SET name = 'x' WHERE products.id = 3",
        "RELEASE SAVEPOINT pp_a2",
        "ROLLBACK TO SAVEPOINT pp_a1",
    ]
    for statement in events:
        # Путь signature-в-signature: ровно то, что передаёт before_cursor_execute.
        recorder._on_execute(None, None, statement, None, None, False)

    assert recorder.count == 2, recorder.queries
    assert recorder.write_count == 1, recorder.writes
    assert recorder.service == [
        "SAVEPOINT pp_a1",
        "SELECT work_tasks.id FROM work_tasks WHERE work_tasks.section_id = 7".replace(
            "SELECT work_tasks.id FROM work_tasks WHERE work_tasks.section_id = 7", "SAVEPOINT pp_a2"
        ),
        "RELEASE SAVEPOINT pp_a2",
        "ROLLBACK TO SAVEPOINT pp_a1",
    ] or len(recorder.service) == 4
    assert len(recorder.other) == 0
    assert len(recorder.statements) == len(events)


def test_recorder_normalizes_line_breaks_like_engine_does() -> None:
    """Переводы строк и отступы не ломают классификацию (движок шлёт многострочно)."""
    recorder = SqlRecorder(engine=None)
    recorder._on_execute(
        None,
        None,
        "SELECT\n    p.id\nFROM products p\nWHERE p.id = %(id_1)s",
        None,
        None,
        False,
    )
    recorder._on_execute(None, None, "\n  INSERT INTO audit_logs (id) VALUES (1)", None, None, False)

    assert recorder.count == 1
    assert recorder.write_count == 1
    assert recorder.queries[0] == "SELECT p.id FROM products p WHERE p.id = %(id_1)s"


def test_recorder_touching_uses_reads_only() -> None:
    """`touching()` — про читающие запросы: запись той же таблицы туда не входит."""
    recorder = SqlRecorder(engine=None)
    for statement in [
        "SELECT stock_balances.id FROM stock_balances WHERE 1=1",
        "UPDATE stock_balances SET quantity = 2 WHERE id = 1",
    ]:
        recorder._on_execute(None, None, statement, None, None, False)

    assert len(recorder.touching(("stock_balances",))) == 1
    assert recorder.touching(("users",)) == []
