"""021_route_stage_section_nullable

The 020_storage_vs_production migration introduced the ``storage_section_id``
column and the ``stage_kind`` enum (production/transit), but did not relax the
``route_stages.section_id`` NOT NULL constraint.  The model and the
``fn_check_route_stage_transit_invariants`` trigger both require
``section_id IS NULL`` for transit stages, so the column must be nullable.

Without this migration the demo/route seeder fails with a NotNullViolation
when inserting a transit stage for a storage section (e.g. WH or WIP_WH).

Revision ID: 021_route_stage_section_nullable
Revises: 020_storage_vs_production
Create Date: 2026-07-01 16:20:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "021_route_stage_section_nullable"
down_revision: Union[str, None] = "020_storage_vs_production"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("route_stages", "section_id", nullable=True)


def downgrade() -> None:
    op.alter_column("route_stages", "section_id", nullable=False)
