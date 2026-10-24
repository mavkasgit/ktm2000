"""Счётчик SQL для регресс-тестов числа запросов (#292/#295/#297/#298).

Слушатели ``before_cursor_execute``/``after_cursor_execute`` на engine. Считать
только SELECT'ы: SAVEPOINT/RELEASE — служебные операторы тестовой транзакции
(``create_savepoint``), а не запросы ручки.
"""

from __future__ import annotations

import re

from sqlalchemy import event


class SqlRecorder:
    """Записать SQL, который engine выполнит внутри блока ``with``."""

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

    @property
    def queries(self) -> list[str]:
        return [
            statement
            for statement in self.statements
            if statement.lstrip().upper().startswith("SELECT")
        ]

    @property
    def selects(self) -> list[str]:
        return self.queries

    @property
    def count(self) -> int:
        return len(self.queries)

    def touching(self, tables: tuple[str, ...]) -> list[str]:
        """SELECT'ы, читающие любую из ``tables`` (по слову после FROM/JOIN)."""
        patterns = [re.compile(rf"\b(?:FROM|JOIN) {re.escape(table)}\b") for table in tables]
        return [
            statement
            for statement in self.queries
            if any(pattern.search(statement) for pattern in patterns)
        ]
