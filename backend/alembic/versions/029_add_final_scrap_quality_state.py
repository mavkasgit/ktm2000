"""029_add_final_scrap_quality_state

Добавляет значение ``final_scrap`` в enum ``stock_quality_state`` для
«окончательного брака» отдельно от обычного ``scrap`` (брак).

Revision ID: 029_final_scrap_qs
Revises: 028_fix_section_type_triggers
Create Date: 2026-07-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "029_final_scrap_qs"
down_revision: Union[str, None] = "028_fix_section_type_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE stock_quality_state ADD VALUE IF NOT EXISTS 'final_scrap'"
    )


def downgrade() -> None:
    # Postgres не поддерживает удаление значений enum без пересоздания типа.
    pass