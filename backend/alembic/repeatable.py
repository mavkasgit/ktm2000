"""Apply Flyway-style repeatable SQL migrations from alembic/repeatable/."""

from __future__ import annotations

from pathlib import Path

from alembic import op

REPEATABLE_DIR = Path(__file__).resolve().parent / "repeatable"


def apply_repeatable_migrations() -> None:
    if not REPEATABLE_DIR.is_dir():
        return
    for path in sorted(REPEATABLE_DIR.glob("R__*.sql")):
        op.execute(path.read_text(encoding="utf-8"))