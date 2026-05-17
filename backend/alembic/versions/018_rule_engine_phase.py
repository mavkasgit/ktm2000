"""add_phase_to_route_selection_rules

Revision ID: 018_rule_engine_phase
Revises: 017_normalization_rules
Create Date: 2026-05-17 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "018_rule_engine_phase"
down_revision: Union[str, None] = "017_normalization_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_selection_rules",
        sa.Column(
            "phase",
            sa.String(20),
            nullable=False,
            server_default="route_select",
        ),
    )
    op.create_index(
        "ix_route_selection_rules_active_profile_phase_priority",
        "route_selection_rules",
        ["is_active", "profile_id", "phase", "priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_route_selection_rules_active_profile_phase_priority")
    op.drop_column("route_selection_rules", "phase")
