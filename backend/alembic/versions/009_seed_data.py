"""seed data: system user, normalization rules defaults

Revision ID: 009_seed_data
Revises: 008_final_polish
Create Date: 2026-05-25 12:07:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = '009_seed_data'
down_revision: Union[str, None] = '008_final_polish'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # System user for dev-mode operations and background tasks.
    # OVERRIDING SYSTEM VALUE is needed because users.id is GENERATED ALWAYS.
    op.execute(
        """
        INSERT INTO users (id, email, password_hash, full_name, role, is_active)
        OVERRIDING SYSTEM VALUE
        VALUES (1, 'system@local', '', 'System User', 'admin', true)
        ON CONFLICT (email) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role
        """
    )
    # Reset the sequence so auto-generated IDs start above 1.
    op.execute("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))")


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE email = 'system@local'")
