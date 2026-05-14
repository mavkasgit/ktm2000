"""add route origin metadata to plan positions

Revision ID: 009_route_origin_metadata
Revises: 008_add_route_sort_order
Create Date: 2026-05-14 18:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "009_route_origin_metadata"
down_revision: Union[str, None] = "008_add_route_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


route_origin_enum = postgresql.ENUM(
    "auto",
    "manual_confirmed",
    "legacy",
    name="plan_position_route_origin",
    create_type=False,
)
route_match_quality_enum = postgresql.ENUM(
    "exact",
    "corrected",
    "unknown",
    name="plan_position_route_match_quality",
    create_type=False,
)
route_match_reason_enum = postgresql.ENUM(
    "wildcard_rule",
    "fallback_first_active",
    "legacy",
    name="plan_position_route_match_reason",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    route_origin_enum.create(bind, checkfirst=True)
    route_match_quality_enum.create(bind, checkfirst=True)
    route_match_reason_enum.create(bind, checkfirst=True)

    op.add_column("plan_positions", sa.Column("route_origin", route_origin_enum, nullable=True))
    op.add_column("plan_positions", sa.Column("route_match_quality", route_match_quality_enum, nullable=True))
    op.add_column("plan_positions", sa.Column("route_match_reason", route_match_reason_enum, nullable=True))
    op.add_column("plan_positions", sa.Column("route_assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plan_positions", sa.Column("route_manual_confirmed_at", sa.DateTime(timezone=True), nullable=True))

    # Legacy backfill: existing assigned routes have unknown source and unknown assignment date.
    op.execute(
        """
        UPDATE plan_positions
        SET route_origin = 'legacy',
            route_match_quality = 'unknown',
            route_match_reason = 'legacy',
            route_assigned_at = NULL,
            route_manual_confirmed_at = NULL
        WHERE route_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("plan_positions", "route_manual_confirmed_at")
    op.drop_column("plan_positions", "route_assigned_at")
    op.drop_column("plan_positions", "route_match_reason")
    op.drop_column("plan_positions", "route_match_quality")
    op.drop_column("plan_positions", "route_origin")

    bind = op.get_bind()
    route_match_reason_enum.drop(bind, checkfirst=True)
    route_match_quality_enum.drop(bind, checkfirst=True)
    route_origin_enum.drop(bind, checkfirst=True)
