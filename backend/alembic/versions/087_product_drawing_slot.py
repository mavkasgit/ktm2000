"""Слот чертежа и происхождение изображения (#463, ADR-0078).

1. ``products.drawing_full`` — третье изображение артикула: чертёж. Слот
   nullable, бэкфилл не нужен: карточки без чертежа остаются валидными, а
   полный просмотр показывает ``photo_full`` (плакат/фото) как запасной
   вариант, пока чертежа нет.

2. ``products.visual_origin`` — ``own`` или ``alias``: чертёж снят для этого
   артикула или взят у эквивалента. Нужен для бейджа «чертёж алиаса»:
   размеры с чужого чертежа обязательно сверяются с текущим артикулом.

Повторный прогон безопасен (конвенция 052: ``stamp`` назад + ``upgrade head``):
колонки создаются и удаляются с ``IF [NOT] EXISTS``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "087_product_drawing_slot"
down_revision: str | None = "086_product_1c_codes_source_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.add_column(
        "products",
        sa.Column("drawing_full", sa.String(length=500), nullable=True),
        if_not_exists=True,
    )
    op.add_column(
        "products",
        sa.Column("visual_origin", sa.String(length=16), nullable=True),
        if_not_exists=True,
    )

    # --- DATA ---

    # --- TRIGGERS ---


def downgrade() -> None:
    op.drop_column("products", "visual_origin", if_exists=True)
    op.drop_column("products", "drawing_full", if_exists=True)
