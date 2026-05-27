"""import domain: import_files, import_batches, import_templates

Revision ID: 006_import_domain
Revises: 005_routes_domain
Create Date: 2026-05-25 12:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '006_import_domain'
down_revision: Union[str, None] = '005_routes_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_if_not_exists(name: str, values: list[str]) -> None:
    """Create a PostgreSQL enum only if it doesn't already exist."""
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :name)").bindparams(name=name)
    ).scalar()
    if not exists:
        postgresql.ENUM(*values, name=name).create(conn)


def upgrade() -> None:
    _create_enum_if_not_exists("import_batch_mode", ["create_plan", "append_to_plan", "replace_draft_from_same_source"])
    _create_enum_if_not_exists("import_batch_status", ["parsed", "failed", "applied", "cancelled"])
    op.create_table('import_files',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('stored_path', sa.String(1000), nullable=True),
        sa.Column('content_type', sa.String(255), nullable=True),
        sa.Column('file_extension', sa.String(20), nullable=False),
        sa.Column('detected_format', sa.String(50), nullable=False),
        sa.Column('file_sha256', sa.String(64), nullable=False, unique=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # import_templates
    op.create_table('import_templates',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=True, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('button_label', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('column_mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('normalization_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # import_batches
    op.create_table('import_batches',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('source_file_id', sa.BigInteger(), sa.ForeignKey('import_files.id'), nullable=False),
        sa.Column('production_plan_id', sa.BigInteger(), sa.ForeignKey('production_plans.id'), nullable=False),
        sa.Column('template_id', sa.BigInteger(), sa.ForeignKey('import_templates.id'), nullable=True),
        sa.Column('rule_profile_id', sa.BigInteger(), sa.ForeignKey('route_rule_profiles.id'), nullable=True),
        sa.Column('mode', postgresql.ENUM("create_plan", "append_to_plan", "replace_draft_from_same_source", name="import_batch_mode", create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM("parsed", "failed", "applied", "cancelled", name="import_batch_status", create_type=False), nullable=False, server_default=sa.text("'parsed'")),
        sa.Column('source_system', sa.String(100), nullable=False, server_default=sa.text("'excel'")),
        sa.Column('sheet_name', sa.String(255), nullable=False),
        sa.Column('header_row_number', sa.BigInteger(), nullable=False),
        sa.Column('total_rows', sa.BigInteger(), nullable=False),
        sa.Column('parsed_rows', sa.BigInteger(), nullable=False),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('rules_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('route_selection_diagnostics', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table('import_batches')
    op.drop_table('import_templates')
    op.drop_table('import_files')

    sa.Enum(name='import_batch_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='import_batch_mode').drop(op.get_bind(), checkfirst=True)
