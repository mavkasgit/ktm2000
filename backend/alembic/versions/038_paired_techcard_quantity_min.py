"""Парные техкарты: инвариант равенства N — «разное кол-во» → min (#67).

Пара висит на подвесе как единая загрузка N×A + N×B, поэтому кол-во на
подвес у обоих компонентов обязано совпадать. Существующие парные техкарты с
quantity_a_per_item != quantity_b_per_item приводятся к общему N = min(оба);
если заполнено только одно из полей — оно копируется в оба. quantity_total,
равный старой сумме a+b, пересчитывается в N×2 (семантика «общее на подвес»).

Revision ID: 038_paired_techcard_quantity_min
Revises: 037_notification_state
Create Date: 2026-08-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "038_paired_techcard_quantity_min"
down_revision: Union[str, None] = "037_notification_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Общее N пары: min(оба), одиночное значение копируется в оба поля.
    # quantity_total («общее на подвес» = N×2) приводится к N×2 для всех
    # парных техкарт, где N известен — независимо от старого значения.
    op.execute(
        """
        UPDATE techcards
        SET
            quantity_a_per_item = COALESCE(
                LEAST(quantity_a_per_item, quantity_b_per_item),
                quantity_a_per_item,
                quantity_b_per_item
            ),
            quantity_b_per_item = COALESCE(
                LEAST(quantity_a_per_item, quantity_b_per_item),
                quantity_a_per_item,
                quantity_b_per_item
            ),
            quantity_total = CASE
                WHEN COALESCE(
                    LEAST(quantity_a_per_item, quantity_b_per_item),
                    quantity_a_per_item,
                    quantity_b_per_item
                ) IS NOT NULL
                THEN COALESCE(
                    LEAST(quantity_a_per_item, quantity_b_per_item),
                    quantity_a_per_item,
                    quantity_b_per_item
                ) * 2
                ELSE quantity_total
            END
        WHERE processing_type = 'paired_processing'
          AND (
              quantity_a_per_item IS DISTINCT FROM quantity_b_per_item
              OR quantity_total IS DISTINCT FROM COALESCE(
                  LEAST(quantity_a_per_item, quantity_b_per_item),
                  quantity_a_per_item,
                  quantity_b_per_item
              ) * 2
          )
        """
    )


def downgrade() -> None:
    # Обратной миграции нет: «разное кол-во» убрано безвозвратно (#67).
    pass
