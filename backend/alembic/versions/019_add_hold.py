"""empty message

Revision ID: 019_add_hold
Revises: 018_make_email_optional
Create Date: 2026-06-23 22:24:25.533629
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '019_add_hold'
down_revision: Union[str, None] = '018_make_email_optional'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    
    # 1. Add 'hold' to defect_status
    result_status = bind.execute(sa.text(
        "SELECT 1 FROM pg_type t "
        "JOIN pg_enum e ON t.oid = e.enumtypid "
        "WHERE t.typname = 'defect_status' AND e.enumlabel = 'hold'"
    )).fetchone()
    
    if not result_status:
        op.execute("COMMIT")
        op.execute("ALTER TYPE defect_status ADD VALUE 'hold'")
        
    # 2. Add 'hold' to defect_decision_type
    result_decision = bind.execute(sa.text(
        "SELECT 1 FROM pg_type t "
        "JOIN pg_enum e ON t.oid = e.enumtypid "
        "WHERE t.typname = 'defect_decision_type' AND e.enumlabel = 'hold'"
    )).fetchone()
    
    if not result_decision:
        op.execute("COMMIT")
        op.execute("ALTER TYPE defect_decision_type ADD VALUE 'hold'")


def downgrade() -> None:
    # Removing enum value is not supported by ALTER TYPE in Postgres without recreating the type.
    # We leave it as pass, which is safe since the value will just remain unused.
    pass
