"""027_section_unified_type

Объединение Section.kind + Section.type в единое Section.type.

- Чистка старых значений sections.type (enum-based)
- Удаление enum-колонки sections.type и типа location_type
- Переименование sections.kind → sections.type
- NOT NULL + server_default='production'

Revision ID: 027_section_unified_type
Revises: 026_cleanup_legacy_tables
Create Date: 2026-07-03 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "027_section_unified_type"
down_revision: Union[str, None] = "026_cleanup_legacy_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Clean up old enum-based sections.type values
    # 'storage' — фантомное значение из R1-бага, маппим на 'scrap'
    op.execute("UPDATE sections SET type = 'scrap' WHERE type::text = 'storage'")
    # Защита от неожиданных значений (laser, welding, painting, assembly, transit и т.п.)
    op.execute(
        "UPDATE sections SET type = 'production' "
        "WHERE type::text NOT IN ('production', 'raw_stock', 'wip_stock', 'finished_stock', 'scrap', 'quarantine')"
    )
    # Финал: NULL → production
    op.execute("UPDATE sections SET type = 'production' WHERE type::text IS NULL")

    # Step 2: Drop old enum column and type
    op.drop_column("sections", "type")
    op.execute("DROP TYPE IF EXISTS location_type")

    # Step 3: Rename kind → type
    op.alter_column("sections", "kind", new_column_name="type")

    # Step 4: Set constraints — NOT NULL + default
    op.alter_column(
        "sections", "type",
        nullable=False,
        server_default=sa.text("'production'"),
    )


def downgrade() -> None:
    # Step 1: Rename type → kind (String(20) column)
    op.alter_column("sections", "type", new_column_name="kind")

    # Step 2: Recreate location_type enum (all 11 values)
    op.execute("""
        CREATE TYPE location_type AS ENUM (
            'raw_stock', 'wip_stock', 'finished_stock', 'production',
            'laser', 'welding', 'painting', 'assembly',
            'scrap', 'quarantine', 'transit'
        )
    """)

    # Step 3: Add old enum-based type column
    op.add_column(
        "sections",
        sa.Column(
            "type",
            postgresql.ENUM(name="location_type", create_type=False),
            nullable=True,
        ),
    )

    # Step 4: Data migration — cast kind values back to enum, handle edge cases
    op.execute("""
        UPDATE sections SET type = (
            CASE
                WHEN kind IN ('raw_stock', 'wip_stock', 'finished_stock', 'production',
                              'laser', 'welding', 'painting', 'assembly',
                              'scrap', 'quarantine', 'transit')
                THEN kind::text::location_type
                WHEN kind = 'storage'
                THEN 'production'::location_type
                ELSE 'production'::location_type
            END
        )
    """)

    # Step 5: SET NOT NULL on new type column
    op.execute("ALTER TABLE sections ALTER COLUMN type SET NOT NULL")

    # Step 6: Restore DEFAULT 'production' on kind
    op.alter_column("sections", "kind", server_default=sa.text("'production'"))
