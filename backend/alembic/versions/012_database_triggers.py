"""database_triggers

Эпик: PL/pgSQL триггеры section_operations и route_stages
Irreversible: no

Revision ID: 012_database_triggers
Revises: 011_hrms
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.db.triggers import DROP_TRIGGER_STATEMENTS, TRIGGER_STATEMENTS

revision: str = "012_database_triggers"
down_revision: Union[str, None] = "011_hrms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    pass

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    for stmt in TRIGGER_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROP_TRIGGER_STATEMENTS:
        op.execute(stmt)