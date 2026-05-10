"""shopfloor core models

Revision ID: b7c7f2f9d91a
Revises: 11eeae284970
Create Date: 2026-05-08 00:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b7c7f2f9d91a"
down_revision: Union[str, None] = "11eeae284970"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE work_task_status ADD VALUE IF NOT EXISTS 'partially_completed'")

    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE entity_type AS ENUM (
                'plan_position', 'section_plan_line', 'work_task',
                'transfer', 'transfer_discrepancy', 'defect',
                'defect_item', 'defect_decision', 'rework_task'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;
        """
    )

    entity_type = postgresql.ENUM(name="entity_type", create_type=False)

    op.create_table(
        "defect_types",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("severity", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("requires_quality_decision", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "transfers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("transfer_no", sa.String(length=100), nullable=False),
        sa.Column("from_task_id", sa.BigInteger(), nullable=False),
        sa.Column("to_task_id", sa.BigInteger(), nullable=False),
        sa.Column("from_section_id", sa.BigInteger(), nullable=False),
        sa.Column("to_section_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("rejected_quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "sent", "accepted", "partially_accepted", "rejected", "cancelled", name="transfer_status"),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("sent_by", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.BigInteger(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sent_quantity > 0", name="ck_transfers_sent_quantity_positive"),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["from_task_id"], ["work_tasks.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["sent_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["to_task_id"], ["work_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_no"),
    )

    op.create_table(
        "transfer_discrepancies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("transfer_id", sa.BigInteger(), nullable=False),
        sa.Column("discrepancy_quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("resolved_quantity", sa.Numeric(precision=14, scale=3), server_default=sa.text("0"), nullable=False),
        sa.Column("unresolved_quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "partially_resolved", "resolved", "cancelled", name="transfer_discrepancy_status"),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("discrepancy_quantity > 0", name="ck_transfer_discrepancy_qty_positive"),
        sa.CheckConstraint("resolved_quantity >= 0", name="ck_transfer_discrepancy_resolved_non_negative"),
        sa.CheckConstraint("unresolved_quantity >= 0", name="ck_transfer_discrepancy_unresolved_non_negative"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["transfer_id"], ["transfers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "movements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("section_plan_line_id", sa.BigInteger(), nullable=True),
        sa.Column("transfer_id", sa.BigInteger(), nullable=True),
        sa.Column("from_section_id", sa.BigInteger(), nullable=True),
        sa.Column("to_section_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "movement_type",
            sa.Enum(
                "issue_to_work",
                "complete",
                "transfer_send",
                "transfer_receive",
                "reject",
                "scrap",
                "return_to_previous",
                "final_release",
                "adjustment",
                name="movement_type",
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_movements_quantity_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["section_plan_line_id"], ["section_plan_lines.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["work_tasks.id"]),
        sa.ForeignKeyConstraint(["to_section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["transfer_id"], ["transfers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movements_task_created_at", "movements", ["task_id", "created_at"], unique=False)

    op.create_table(
        "defects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("section_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("movement_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "decision_required",
                "rework_task_created",
                "scrapped",
                "returned",
                "accepted_with_deviation",
                "closed",
                name="defect_status",
            ),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("responsible_section_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["movement_id"], ["movements.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["responsible_section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["work_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "defect_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("defect_id", sa.BigInteger(), nullable=False),
        sa.Column("defect_type_id", sa.BigInteger(), nullable=True),
        sa.Column("defect_type_code_snapshot", sa.String(length=100), nullable=True),
        sa.Column("defect_type_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("subtype_code", sa.String(length=100), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_defect_items_qty_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["defect_id"], ["defects.id"]),
        sa.ForeignKeyConstraint(["defect_type_id"], ["defect_types.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "defect_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("defect_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "decision_type",
            sa.Enum(
                "scrap",
                "rework_current",
                "return_previous",
                "quality_hold",
                "accept_with_deviation",
                name="defect_decision_type",
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("target_section_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_defect_decisions_qty_positive"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["defect_id"], ["defects.id"]),
        sa.ForeignKeyConstraint(["target_section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rework_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("defect_id", sa.BigInteger(), nullable=False),
        sa.Column("source_task_id", sa.BigInteger(), nullable=False),
        sa.Column("section_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "completed", "cancelled", name="rework_task_status"),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_rework_tasks_qty_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["defect_id"], ["defects.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["source_task_id"], ["work_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "entity_comments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("comment_type", sa.String(length=50), server_default=sa.text("'note'"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_comments_entity", "entity_comments", ["entity_type", "entity_id", "created_at"], unique=False)

    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_path", sa.String(length=1000), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "attachment_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("attachment_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", postgresql.ENUM(name="entity_type", create_type=False), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attachment_id", "entity_type", "entity_id", name="uq_attachment_links_target"),
    )

    op.create_table(
        "transfer_discrepancy_defect_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("transfer_discrepancy_id", sa.BigInteger(), nullable=False),
        sa.Column("defect_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_discrepancy_defect_item_qty_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["defect_item_id"], ["defect_items.id"]),
        sa.ForeignKeyConstraint(["transfer_discrepancy_id"], ["transfer_discrepancies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("transfer_discrepancy_defect_items")
    op.drop_table("attachment_links")
    op.drop_table("attachments")
    op.drop_index("ix_entity_comments_entity", table_name="entity_comments")
    op.drop_table("entity_comments")
    op.drop_table("rework_tasks")
    op.drop_table("defect_decisions")
    op.drop_table("defect_items")
    op.drop_table("defects")
    op.drop_index("ix_movements_task_created_at", table_name="movements")
    op.drop_table("movements")
    op.drop_table("transfer_discrepancies")
    op.drop_table("transfers")
    op.drop_table("defect_types")

    sa.Enum(name="rework_task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="defect_decision_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="defect_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="movement_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transfer_discrepancy_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transfer_status").drop(op.get_bind(), checkfirst=True)
    op.execute("DROP TYPE IF EXISTS entity_type")
