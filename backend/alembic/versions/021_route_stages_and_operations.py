"""add route_stages + route_operations, backfill from route_steps

Revision ID: 021_route_stages_and_operations
Revises: 020_merge_heads
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa


revision = "021_route_stages_and_operations"
down_revision = "31ad3a8c872d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_stages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("production_routes.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.BigInteger(), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("is_significant", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("norm_time_minutes", sa.Integer(), nullable=True),
        sa.Column("requires_acceptance", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allow_parallel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("route_step_id", sa.BigInteger(), sa.ForeignKey("route_steps.id"), nullable=True),
        sa.UniqueConstraint("route_id", "sequence", name="uq_route_stages_sequence"),
    )

    op.create_table(
        "route_operations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("route_stage_id", sa.BigInteger(), sa.ForeignKey("route_stages.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("operation_code", sa.String(length=100), nullable=True),
        sa.Column("operation_name", sa.String(length=255), nullable=False),
        sa.UniqueConstraint("route_stage_id", "sequence", name="uq_route_operations_sequence"),
    )

    op.add_column(
        "section_plan_lines",
        sa.Column("route_stage_id", sa.BigInteger(), sa.ForeignKey("route_stages.id"), nullable=True),
    )

    bind = op.get_bind()
    route_steps = bind.execute(
        sa.text(
            """
            SELECT id, route_id, sequence, section_id, operation_code, operation_name,
                   norm_time_minutes, requires_acceptance,
                   allow_parallel, is_final
            FROM route_steps
            ORDER BY route_id, sequence
            """
        )
    ).fetchall()

    groups: dict[tuple, list] = {}
    for step in route_steps:
        group_key = (
            step.route_id,
            step.section_id,
            f"__solo_{step.id}",
        )
        groups.setdefault(group_key, []).append(step)

    for (route_id, section_id, _cog), steps in groups.items():
        first = min(steps, key=lambda s: s.sequence)
        is_final = any(s.is_final for s in steps)
        stage_result = bind.execute(
            sa.text(
                """
                INSERT INTO route_stages (
                    route_id, sequence, section_id,
                    is_significant, norm_time_minutes, requires_acceptance,
                    allow_parallel, is_final, sort_order, route_step_id
                )
                VALUES (:route_id, :sequence, :section_id,
                        :is_significant, :norm_time_minutes, :requires_acceptance,
                        :allow_parallel, :is_final, 0, :route_step_id)
                RETURNING id
                """
            ),
            {
                "route_id": route_id,
                "sequence": first.sequence,
                "section_id": section_id,
                "is_significant": False,
                "norm_time_minutes": first.norm_time_minutes,
                "requires_acceptance": first.requires_acceptance,
                "allow_parallel": first.allow_parallel,
                "is_final": is_final,
                "route_step_id": first.id,
            },
        ).first()
        stage_id = stage_result[0]

        for op_idx, step in enumerate(sorted(steps, key=lambda s: s.sequence), start=1):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO route_operations (
                        route_stage_id, sequence, operation_code, operation_name
                    )
                    VALUES (:route_stage_id, :sequence, :operation_code, :operation_name)
                    """
                ),
                {
                    "route_stage_id": stage_id,
                    "sequence": op_idx,
                    "operation_code": step.operation_code,
                    "operation_name": step.operation_name,
                },
            )

    bind.execute(
        sa.text(
            """
            UPDATE section_plan_lines spl
            SET route_stage_id = rst.id
            FROM route_steps rs
            JOIN route_stages rst ON rst.route_step_id = rs.id
            WHERE spl.route_step_id = rs.id
              AND spl.route_stage_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("section_plan_lines", "route_stage_id")
    op.drop_table("route_operations")
    op.drop_table("route_stages")
