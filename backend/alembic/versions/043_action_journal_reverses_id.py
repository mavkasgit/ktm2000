"""action_journal + переименование compensates_tx_id → reverses_id.

Эпик Reversal (ADR-0019, тикет #113):
1. Таблица ``action_journal`` — единый журнал обратимых доменных действий.
2. ``stock_transactions.compensates_tx_id`` → ``reverses_id`` (единая
   связь отката в ledger); net-арифметика не меняется.
3. ``stock_transactions.action_id`` — связь проводки с действием,
   породившим её (проводки одной операции — один action_id).

Irreversible: no

Revision ID: 043_action_journal_reverses_id
Revises: 042_sync_unique_code_indexes
Create Date: 2026-08-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "043_action_journal_reverses_id"
down_revision: Union[str, None] = "042_sync_unique_code_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('action_journal',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('action_type', sa.String(length=50), nullable=False),
    sa.Column('ref_id', sa.BigInteger(), nullable=True),
    sa.Column('actor', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('depends_on', postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('reversed_by_action_id', sa.BigInteger(), nullable=True),
    sa.Column('amends_action_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['amends_action_id'], ['action_journal.id'], name=op.f('fk_action_journal_amends_action_id_action_journal')),
    sa.ForeignKeyConstraint(['reversed_by_action_id'], ['action_journal.id'], name=op.f('fk_action_journal_reversed_by_action_id_action_journal')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_action_journal'))
    )

    op.add_column('stock_transactions', sa.Column('action_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(op.f('fk_stock_transactions_action_id_action_journal'), 'stock_transactions', 'action_journal', ['action_id'], ['id'])
    op.create_index(op.f('ix_stock_transactions_action_id'), 'stock_transactions', ['action_id'], unique=False)

    op.alter_column('stock_transactions', 'compensates_tx_id', new_column_name='reverses_id')
    op.execute(
        "ALTER TABLE stock_transactions RENAME CONSTRAINT "
        "fk_stock_transactions_compensates_tx_id_stock_transactions "
        "TO fk_stock_transactions_reverses_id_stock_transactions"
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.execute(
        "ALTER TABLE stock_transactions RENAME CONSTRAINT "
        "fk_stock_transactions_reverses_id_stock_transactions "
        "TO fk_stock_transactions_compensates_tx_id_stock_transactions"
    )
    op.alter_column('stock_transactions', 'reverses_id', new_column_name='compensates_tx_id')

    op.drop_index(op.f('ix_stock_transactions_action_id'), table_name='stock_transactions')
    op.drop_constraint(op.f('fk_stock_transactions_action_id_action_journal'), 'stock_transactions', type_='foreignkey')
    op.drop_column('stock_transactions', 'action_id')

    op.drop_table('action_journal')
