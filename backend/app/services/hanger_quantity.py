from __future__ import annotations

import math
from decimal import Decimal


def adjust_quantity_to_hanger(
    quantity: Decimal, quantity_per_hanger: int | None
) -> Decimal | None:
    """Округляет количество вверх до кратного quantity_per_hanger.

    Args:
        quantity: Исходное количество (обычно из Excel).
        quantity_per_hanger: Сколько штук помещается на одном подвесе.

    Returns:
        Скорректированное количество, или None если:
        - quantity_per_hanger не задан или <= 0
        - quantity <= 0
        - quantity уже кратно quantity_per_hanger (округление не требуется)
    """
    if not quantity_per_hanger or quantity_per_hanger <= 0:
        return None

    if quantity <= 0:
        return None

    remainder = quantity % quantity_per_hanger
    if remainder == 0:
        return None  # Уже кратно

    hangers = math.ceil(quantity / quantity_per_hanger)
    return Decimal(hangers * quantity_per_hanger)
