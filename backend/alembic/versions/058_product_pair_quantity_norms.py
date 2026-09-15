"""Нормы парных профилей из файла справочника → product_pairs (#177, Q13).

В рабочем файле ``excel/final_catalog.xlsx`` нормы пар лежали в колонке
«Парный профиль» рядом со SKU партнёра («ЮП-2616, 30»). Импорт такой формат
не читает (#177, Q1), поэтому значения существовали только в файле — их
переносят в ``product_pairs.quantity_per_hanger``, где паре и место: ручная N
по длинам, ``auto`` считает движок живьём.

Все пять пар имеют единственную длину 2750 мм у обоих артикулов, поэтому
пересечение длин A∩B = {2750} и ключ нормы однозначен (вне пересечения пара
не существует).

Идемпотентна: пишет только пары с пустым словарём норм и только тем связям,
у которых 2750 мм есть у обоих артикулов — отсутствующие SKU и пары с уже
проставленной нормой пропускаются.

Irreversible: partially — downgrade очищает словарь норм этих пар, но вернуть
прежнее содержимое не может (нормы пришли из файла, а не из БД).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "058_product_pair_quantity_norms"
down_revision: Union[str, None] = "057_plan_change_set_applied_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LENGTH_MM = 2750

# (SKU A, SKU B, ручная N на 2750 мм) — значения с обеих сторон файла совпадают.
_PAIR_NORMS: list[tuple[str, str, int]] = [
    ("ЮП-2604", "ЮП-2616", 30),
    ("ЮП-2616", "ЮП-3158", 32),
    ("ЮП-2616", "ЮП-3098", 35),
    ("ЮП-2695", "ЮП-2878", 24),
    ("ЮП-3452", "ЮП-3453", 26),
]

_PAIR_MATCH_SQL = """
    products a, products b
    WHERE a.sku = :sku_a AND b.sku = :sku_b
      AND pp.product_a_id = LEAST(a.id, b.id)
      AND pp.product_b_id = GREATEST(a.id, b.id)
"""

_HAS_LENGTH_SQL = """
      AND EXISTS (
          SELECT 1 FROM product_lengths l
          WHERE l.product_id = a.id AND l.length_mm = :length_mm
      )
      AND EXISTS (
          SELECT 1 FROM product_lengths l
          WHERE l.product_id = b.id AND l.length_mm = :length_mm
      )
"""

# Типы bind-параметров: jsonb_build_object('manual', :manual) обязан получить
# int, а не текст (иначе в JSONB уедет строка «30»).
_PARAM_TYPES: dict[str, object] = {"manual": sa.Integer, "length_mm": sa.Float}


def _execute(sql: str, sku_a: str, sku_b: str, **values: object) -> None:
    """Выполнить апдейт пары, связав только те параметры, что есть в тексте SQL."""
    binds = [sa.bindparam("sku_a", sku_a), sa.bindparam("sku_b", sku_b)]
    for name, value in values.items():
        binds.append(sa.bindparam(name, value, type_=_PARAM_TYPES[name]))
    op.execute(sa.text(sql).bindparams(*binds))


def upgrade() -> None:
    for sku_a, sku_b, manual in _PAIR_NORMS:
        _execute(
            "UPDATE product_pairs pp "
            "SET quantity_per_hanger = jsonb_build_object("
            "    '2750', jsonb_build_object('manual', :manual)"
            ") "
            "FROM" + _PAIR_MATCH_SQL + _HAS_LENGTH_SQL +
            "  AND pp.quantity_per_hanger = '{}'::jsonb",
            sku_a,
            sku_b,
            manual=manual,
            length_mm=float(_LENGTH_MM),
        )


def downgrade() -> None:
    for sku_a, sku_b, manual in _PAIR_NORMS:
        _execute(
            "UPDATE product_pairs pp "
            "SET quantity_per_hanger = '{}'::jsonb "
            "FROM" + _PAIR_MATCH_SQL +
            "  AND pp.quantity_per_hanger = jsonb_build_object("
            "      '2750', jsonb_build_object('manual', :manual)"
            "  )",
            sku_a,
            sku_b,
            manual=manual,
        )
