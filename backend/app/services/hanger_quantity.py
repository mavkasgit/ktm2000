from __future__ import annotations

import math
from decimal import Decimal

from app.seeds.canon.models import HangerRoundingRule

# Типизированное правило из канона (ADR-0004). Сервис не импортирует plant_policies.
from app.seeds.canon.registry import build_plant_config as _build

_DEFAULT_RULE: HangerRoundingRule = _build().production.hanger_rounding


def adjust_quantity_to_hanger(
    quantity: Decimal,
    quantity_per_hanger: int | None,
    hanger_rounding: HangerRoundingRule | None = None,
) -> Decimal | None:
    """Округляет количество вверх до кратного quantity_per_hanger.

    Правило округления настраивается данными (канон заводской конфигурации,
    ADR-0004), а не зашито в код. При отключённом правиле
    возвращает исходное количество без изменений.

    Args:
        quantity: Исходное количество (обычно из Excel).
        quantity_per_hanger: Сколько штук помещается на одном подвесе.
        hanger_rounding: Правило округления (из канона). Если None — default.

    Returns:
        Скорректированное количество, или None если:
        - quantity_per_hanger не задан или <= 0
        - quantity <= 0
        - quantity уже кратно quantity_per_hanger (округление не требуется)
    """
    rule = hanger_rounding if hanger_rounding is not None else _DEFAULT_RULE
    if not rule.enabled:
        return quantity

    if not quantity_per_hanger or quantity_per_hanger <= 0:
        return None

    if quantity <= 0:
        return None

    remainder = quantity % quantity_per_hanger
    if remainder == 0:
        return None  # Уже кратно

    hangers = math.ceil(quantity / quantity_per_hanger)
    return Decimal(hangers * quantity_per_hanger)
