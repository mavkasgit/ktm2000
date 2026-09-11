"""plan_change_sets.applied_at: последний применённый батч плана (#172).

«Последний применённый» для LIFO-отката определяется моментом применения,
а не порядком загрузки файла (created_at батча) и не audit_logs: список
файлов плана отдаёт applied_at напрямую.

Irreversible: no

Revision ID: 057_plan_change_set_applied_at
Revises: 056_action_journal_status_length
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op


revision: str = "057_plan_change_set_applied_at"
down_revision: Union[str, None] = "056_action_journal_status_length"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Идемпотентно: тесты миграций перезапускают «stamp назад → upgrade head»
    # на живой схеме (конвенция 051/052) — повторный прогон обязан проходить.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'plan_change_sets'
                  AND column_name = 'applied_at'
            ) THEN
                ALTER TABLE plan_change_sets
                    ADD COLUMN applied_at TIMESTAMP WITH TIME ZONE;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE plan_change_sets DROP COLUMN IF EXISTS applied_at")
