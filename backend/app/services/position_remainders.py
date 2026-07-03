from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.stock.models import QualityState, StockBalance


async def compute_available_remainder_quantity(
    db: AsyncSession,
    *,
    effective_product_id: int | None,
    route_steps: list[dict],
    position_id: int | None = None,
) -> float:
    """Вернуть сумму остатков на складах для продукта.

    После Этапа 7 рефакторинга Stock Ledger возвращает сумму
    StockBalance.balance_qty для продукта по всем локациям.

    Args:
        db: Асинхронная сессия SQLAlchemy.
        effective_product_id: ID продукта.
        route_steps: Не используется (заглушка совместимости).
        position_id: Не используется (заглушка совместимости).

    Returns:
        Сумма остатков в виде float.
        Возвращает 0.0 если effective_product_id is None.
    """
    if effective_product_id is None:
        return 0.0

    total = await db.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
            StockBalance.product_id == effective_product_id,
            StockBalance.balance_qty > 0,
            StockBalance.quality_state == QualityState.GOOD,
        )
    )

    return float(total or 0)
