"""Перевести производственные планы на модель нормальных длин.

Существующие планы помечаются версией 1 и остаются доступными только для
чтения до повторного импорта. Новые строки получают текущую версию 2.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "060_length_model_cutover"
down_revision: Union[str, None] = "059_product_length_raw_length"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("production_plans")
    }
    if "length_model_version" not in columns:
        op.add_column(
            "production_plans",
            sa.Column(
                "length_model_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    op.alter_column(
        "production_plans",
        "length_model_version",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("2"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("production_plans")
    }
    if "length_model_version" in columns:
        op.drop_column("production_plans", "length_model_version")
