"""add username to users

Revision ID: 013_add_username
Revises: 012_audit_logs
Create Date: 2026-06-10 01:14:58.872174
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '013_add_username'
down_revision: Union[str, None] = '012_audit_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавляем колонку как nullable=True
    op.add_column('users', sa.Column('username', sa.String(length=255), nullable=True))
    # 2. Заполняем username значением из email (часть до символа '@')
    op.execute("UPDATE users SET username = split_part(email, '@', 1)")
    # 3. Устанавливаем nullable=False
    op.alter_column('users', 'username', nullable=False)
    # 4. Создаем ограничение уникальности
    op.create_unique_constraint('users_username_key', 'users', ['username'])

    # 5. Создаем таблицу user_sections
    op.create_table(
        'user_sections',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'section_id')
    )

    # 6. Переносим данные из users.section_id в user_sections
    op.execute("INSERT INTO user_sections (user_id, section_id) SELECT id, section_id FROM users WHERE section_id IS NOT NULL")


def downgrade() -> None:
    op.drop_table('user_sections')
    op.drop_constraint('users_username_key', 'users', type_='unique')
    op.drop_column('users', 'username')
