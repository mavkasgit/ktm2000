"""Чистый бюджет передач — формулы без БД/ORM/примитива (только decimal).

Семантика (тикет #106):
- ``remaining_plain(completed, transferred)`` — сколько ещё можно передать
  с обычного производственного задания: только уже завершённое количество
  минус уже переданное. ``received`` в бюджете НЕ участвует (намеренное
  breaking-изменение: раньше ``completed + received - transferred``).
- ``remaining_transform(produced, transferred)`` — сколько ещё можно
  передать выхода трансформирующего задания: фактически раскроенное
  (уже закапленное ``min(output_quantity, produced_by_group)`` на уровне
  ``build_outputs_progress``) минус уже переданное по размеру. Инвариант D2.
- ``remaining_stock(plan_remaining, physical_stock)`` — складская передача:
  нельзя больше плана позиции и больше физического остатка.

Все функции клампят в ноль — бюджет не бывает отрицательным.
"""
from __future__ import annotations

from decimal import Decimal


def remaining_plain(completed: Decimal, transferred: Decimal) -> Decimal:
    """Остаток к передаче с обычного задания: ``max(0, completed - transferred)``."""
    return max(Decimal("0"), completed - transferred)


def remaining_transform(produced: Decimal, transferred: Decimal) -> Decimal:
    """Остаток к передаче выхода трансформации: ``max(0, produced - transferred)``.

    ``produced`` приходит уже закапленным ``min(output_quantity,
    produced_by_group)`` из ``build_outputs_progress`` — кап здесь не
    дублируется.
    """
    return max(Decimal("0"), produced - transferred)


def remaining_stock(plan_remaining: Decimal, physical_stock: Decimal) -> Decimal:
    """Складской остаток к передаче: ``min(plan_remaining, physical_stock)``."""
    return min(plan_remaining, physical_stock)
