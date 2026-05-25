"""merge icon_color and task_operation_override

Revision ID: 2fb9e051a661
Revises: 020_task_operation_override, 021_icon_color_ops
Create Date: 2026-05-25 03:09:23.805223
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '2fb9e051a661'
down_revision: Union[str, None] = ('020_task_operation_override', '021_icon_color_ops')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
