"""remove_route_steps_and_move_to_stages

Revision ID: 05d055e2043d
Revises: 021_route_stages_and_operations
Create Date: 2026-06-03 23:09:53.250732
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '05d055e2043d'
down_revision: Union[str, None] = '021_route_stages_and_operations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def drop_foreign_key_if_exists(table: str, column: str):
    bind = op.get_bind()
    sql = f"""
        SELECT tc.constraint_name 
        FROM information_schema.table_constraints AS tc 
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' 
          AND tc.table_name = '{table}' 
          AND kcu.column_name = '{column}';
    """
    results = bind.execute(sa.text(sql)).fetchall()
    for row in results:
        op.drop_constraint(row[0], table, type_='foreignkey')


def upgrade() -> None:
    # 1. Add route_stage_id columns as nullable
    op.add_column("work_tasks", sa.Column("route_stage_id", sa.BigInteger(), sa.ForeignKey("route_stages.id"), nullable=True))
    op.add_column("warehouse_remainders", sa.Column("route_stage_id", sa.BigInteger(), sa.ForeignKey("route_stages.id"), nullable=True))

    # 2. Backfill route_stage_id in section_plan_lines, work_tasks, warehouse_remainders
    bind = op.get_bind()

    # Сначала обновим по точному совпадению (для соло-шагов и первых шагов групп)
    bind.execute(
        sa.text(
            """
            UPDATE section_plan_lines spl
            SET route_stage_id = rst.id
            FROM route_stages rst
            WHERE spl.route_step_id = rst.route_step_id
              AND spl.route_stage_id IS NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE work_tasks wt
            SET route_stage_id = rst.id
            FROM route_stages rst
            WHERE wt.route_step_id = rst.route_step_id
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE warehouse_remainders wr
            SET route_stage_id = rst.id
            FROM route_stages rst
            WHERE wr.route_step_id = rst.route_step_id
            """
        )
    )

    # Затем для остальных шагов, которые были объединены в группы по combined_op_group
    for table_name in ["section_plan_lines", "work_tasks", "warehouse_remainders"]:
        bind.execute(
            sa.text(
                f"""
                UPDATE {table_name} t
                SET route_stage_id = rst.id
                FROM route_steps rs
                JOIN route_steps first_rs ON first_rs.route_id = rs.route_id
                    AND first_rs.section_id = rs.section_id
                    AND first_rs.combined_op_group = rs.combined_op_group
                JOIN route_stages rst ON rst.route_step_id = first_rs.id
                WHERE t.route_step_id = rs.id
                  AND t.route_stage_id IS NULL
                  AND rs.combined_op_group IS NOT NULL
                  AND first_rs.id = (
                      SELECT min(id) FROM route_steps
                      WHERE route_id = rs.route_id
                        AND section_id = rs.section_id
                        AND combined_op_group = rs.combined_op_group
                  )
                """
            )
        )

    # 3. Handle non-nullability and unique constraints
    # Delete uq_section_plan_lines_step and create uq_section_plan_lines_stage
    op.drop_constraint("uq_section_plan_lines_step", "section_plan_lines", type_="unique")
    
    # Make route_stage_id non-nullable in section_plan_lines and work_tasks
    op.alter_column("section_plan_lines", "route_stage_id", nullable=False)
    op.alter_column("work_tasks", "route_stage_id", nullable=False)

    op.create_unique_constraint(
        "uq_section_plan_lines_stage",
        "section_plan_lines",
        ["internal_plan_id", "plan_position_id", "route_stage_id"]
    )

    # 4. Drop old foreign keys and route_step_id columns
    drop_foreign_key_if_exists("section_plan_lines", "route_step_id")
    drop_foreign_key_if_exists("work_tasks", "route_step_id")
    drop_foreign_key_if_exists("warehouse_remainders", "route_step_id")
    drop_foreign_key_if_exists("route_stages", "route_step_id")

    op.drop_column("section_plan_lines", "route_step_id")
    op.drop_column("work_tasks", "route_step_id")
    op.drop_column("warehouse_remainders", "route_step_id")
    op.drop_column("route_stages", "route_step_id")

    # 5. Drop route_steps table
    op.drop_table("route_steps")


def downgrade() -> None:
    # Downgrade is not critical since it's a final refactoring, but let's write a basic draft or pass
    # Given database schema changes and dropped data, a true downgrade is destructive.
    # We will raise NotImplementedError or just do pass. Raising error is cleaner.
    raise NotImplementedError("Downgrade from final RouteStage + RouteOperation refactoring is not supported.")

