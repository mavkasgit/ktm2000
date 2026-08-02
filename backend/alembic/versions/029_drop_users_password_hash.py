"""Drop users.password_hash — SSO-only auth, no local passwords (#28)."""
from alembic import op
import sqlalchemy as sa

revision = "029_drop_users_password_hash"
down_revision = "028_product_attributes_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=False, server_default=""))
    op.alter_column("users", "password_hash", server_default=None)
