"""Счётчик SQL для регресс-тестов числа запросов (#292/#295/#297/#298/#381).

Слушатели ``before_cursor_execute``/``after_cursor_execute`` на engine.

Что считается и почему. Ручка модели — **читает** она или **пишет**, поэтому
statements разделены на два видимых счётчика:

* ``queries`` / ``count`` / ``selects`` — только ``SELECT`` (исторический
  фильтр без читающих CTE: см. докстринг ``classify_statement``);
* ``writes`` / ``write_count`` — ``INSERT``/``UPDATE``/``DELETE`` (и CTE-запись);
* служебные операторы тестовой транзакции (``SAVEPOINT``, ``RELEASE``,
  ``ROLLBACK TO SAVEPOINT``, ``SET``, ``BEGIN``, ``COMMIT``, ``ROLLBACK``) — не
  попадают никуда: это обвязка фикстуры «транзакция на тест», а не работа ручки;
* всё остальное (DDL, ``PRAGMA``, ``ANALYZE``) — в ``statements`` и в
  классификации ``other``; отдельно не считается, потому что в скоупе счётчика
  продуктовый код DDL не выполняет.

Историческая дыра, закрытая #381: до неё в `.count` попадали только ``SELECT``,
а записей счётчик не видел вовсе — регресс удвоения `INSERT` на путях записи
проходил молча (кандидат B-N11). `count` от добавления `writes` **не меняется**:
фильтр SELECT остался тем же, поэтому уже снятые потолки (#297/#298/#295)
переписывать не нужно.

Отдельная копия счётчика живёт в `tests/test_section_board_batching_293.py` —
намеренно другая семантика (там считаются ВСЕ statements, а `flush()` виден
как `SAVEPOINT`, и тест меряет именно число flush'ей). Не унифицировать без
перемера того теста.
"""

from __future__ import annotations

import re

from sqlalchemy import event

#: Префиксы, которые относятся к обвязке тестовой транзакции, а не к ручке.
SERVICE_STATEMENT_PREFIXES = (
    "SAVEPOINT",
    "RELEASE",
    "ROLLBACK TO SAVEPOINT",
    "SET",
    "BEGIN",
    "START TRANSACTION",
    "COMMIT",
    "ROLLBACK",
)

_SELECT = "select"
_WRITE = "write"
_SERVICE = "service"
_OTHER = "other"

#: Запись внутри CTE: `WITH x AS (INSERT … RETURNING …) SELECT …` — префикс
#: `WITH`, а работа писает. Ищем ключевое слово изменения данных как отдельное
#: слово; ложное срабатывание возможно только на литерале вида
#: `WITH … ('INSERT INTO …')`, а таких запросов в скоупе счётчика нет.
_CTE_WRITE = re.compile(r"\b(?:INSERT|UPDATE|DELETE)\b")


def classify_statement(statement: str) -> str:
    """Класс SQL-текста: ``select`` | ``write`` | ``service`` | ``other``.

    Нормализация та же, что у записанных statements: схлопнутые пробелы и
    верхний регистр. Пустая строка — ``other`` (нечего классифицировать).

    ``select`` — ровно исторический фильтр «текст начинается с SELECT», без
    читающих CTE. Это не забывчивость, а контракт: потолки #295/#297/#298
    сняты с этим фильтром, и включение в него `WITH … SELECT` передвинуло бы
    уже зафиксированные числа. Читающий `WITH` поэтому живёт в ``other`` —
    то есть виден, но не считается; если понадобится мерить CTE-выборку,
    это отдельный тикет с переснятыми потолками.
    """
    normalized = " ".join(statement.split()).upper()
    if not normalized:
        return _OTHER
    if normalized.startswith(SERVICE_STATEMENT_PREFIXES):
        return _SERVICE
    if normalized.startswith(("INSERT", "UPDATE", "DELETE")):
        return _WRITE
    if normalized.startswith("WITH"):
        return _WRITE if _CTE_WRITE.search(normalized) else _OTHER
    if normalized.startswith("SELECT"):
        return _SELECT
    return _OTHER


class SqlRecorder:
    """Записать SQL, который engine выполнит внутри блока ``with``.

    ``statements`` — весь сырой поток (нормализованный), ``queries``/``count`` —
    читающие запросы, ``writes``/``write_count`` — запросы на запись. Пороги
    регресс-тестов держатся на ``count``; ``writes`` — второй счётчик для путей
    записи, а не замена первого.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self) -> SqlRecorder:
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(" ".join(statement.split()))

    def _of_class(self, kind: str) -> list[str]:
        return [statement for statement in self.statements if classify_statement(statement) == kind]

    @property
    def queries(self) -> list[str]:
        """Читающие запросы (``SELECT`` и читающие CTE)."""
        return self.selects

    @property
    def selects(self) -> list[str]:
        """То же, что ``queries`` — имя для читателя тестов (#297/#298)."""
        return self._of_class(_SELECT)

    @property
    def writes(self) -> list[str]:
        """Запросы на запись: ``INSERT``/``UPDATE``/``DELETE`` и CTE-запись (#381)."""
        return self._of_class(_WRITE)

    @property
    def service(self) -> list[str]:
        """Обвязка тестовой транзакции — то, что счётчик сознательно не считает."""
        return self._of_class(_SERVICE)

    @property
    def other(self) -> list[str]:
        """Всё прочее (DDL и т. п.): видно, что не потерялось между классами."""
        return self._of_class(_OTHER)

    @property
    def count(self) -> int:
        return len(self.queries)

    @property
    def write_count(self) -> int:
        return len(self.writes)

    def touching(self, tables: tuple[str, ...]) -> list[str]:
        """SELECT'ы, читающие любую из ``tables`` (по слову после FROM/JOIN)."""
        patterns = [re.compile(rf"\b(?:FROM|JOIN) {re.escape(table)}\b") for table in tables]
        return [
            statement
            for statement in self.queries
            if any(pattern.search(statement) for pattern in patterns)
        ]
