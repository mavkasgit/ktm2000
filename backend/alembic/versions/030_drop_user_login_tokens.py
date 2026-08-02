"""Drop user_login_tokens table — OTP flow removed (#27), SSO-only (#28)."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "030_drop_user_login_tokens"
down_revision: Union[str, None] = "029_drop_users_password_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("user_login_tokens")


def downgrade() -> None:
    op.create_table(
        "user_login_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("is_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_login_tokens_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_login_tokens")),
        sa.UniqueConstraint("token", name=op.f("uq_user_login_tokens_token")),
    )
