"""add work_task cache constraints and transfer quantity guards

Revision ID: c8d3e4f5a6b7
Revises: b7c7f2f9d91a
Create Date: 2026-05-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c8d3e4f5a6b7"
down_revision: Union[str, None] = "b7c7f2f9d91a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # WorkTask cache columns must be non-negative
    op.create_check_constraint(
        "ck_work_tasks_cached_available_quantity_non_negative",
        "work_tasks",
        "cached_available_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_issued_quantity_non_negative",
        "work_tasks",
        "cached_issued_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_in_work_quantity_non_negative",
        "work_tasks",
        "cached_in_work_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_completed_quantity_non_negative",
        "work_tasks",
        "cached_completed_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_transferred_quantity_non_negative",
        "work_tasks",
        "cached_transferred_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_received_quantity_non_negative",
        "work_tasks",
        "cached_received_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_rejected_quantity_non_negative",
        "work_tasks",
        "cached_rejected_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_cached_remaining_quantity_non_negative",
        "work_tasks",
        "cached_remaining_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_work_tasks_planned_quantity_positive",
        "work_tasks",
        "planned_quantity > 0",
    )

    # Transfer nullable quantity fields must be non-negative when present
    op.create_check_constraint(
        "ck_transfers_accepted_quantity_non_negative",
        "transfers",
        "accepted_quantity IS NULL OR accepted_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_transfers_rejected_quantity_non_negative",
        "transfers",
        "rejected_quantity IS NULL OR rejected_quantity >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transfers_rejected_quantity_non_negative", "transfers")
    op.drop_constraint("ck_transfers_accepted_quantity_non_negative", "transfers")
    op.drop_constraint("ck_work_tasks_planned_quantity_positive", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_remaining_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_rejected_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_received_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_transferred_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_completed_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_in_work_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_issued_quantity_non_negative", "work_tasks")
    op.drop_constraint("ck_work_tasks_cached_available_quantity_non_negative", "work_tasks")
