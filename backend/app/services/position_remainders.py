from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spg_remainder import SpgRemainder


async def compute_available_remainder_quantity(
    db: AsyncSession,
    *,
    effective_product_id: int | None,
    route_steps: list[dict],
    position_id: int | None = None,
) -> float:
    """Вернуть сумму remainder_quantity совместимых SpgRemainder для позиции плана.

    Совместимость определяется по правилу prefix-match: каждый stage в
    completed_stages_json остатка должен соответствовать началу маршрута
    позиции (та же sequence, та же section_id, operation_code ∈ allowed).

    Используется на страницах «Планирование» и «Контроль выполнения» для
    отображения индикатора доступных остатков в колонке «Артикул».

    Args:
        db: Асинхронная сессия SQLAlchemy.
        effective_product_id: ID продукта позиции (или None, если не резолвится).
        route_steps: Список шагов маршрута. Каждый шаг — dict с полями:
            - sequence (int): порядковый номер этапа
            - section_id (int | None): ID секции этапа
            - operation_codes (set[str | None]): допустимые коды операций этапа
        position_id: Если задан, остатки зарезервированные под эту позицию
            тоже учитываются (как и свободные).

    Returns:
        Сумма remainder_quantity совместимых остатков в виде float.
        Возвращает 0.0 если effective_product_id is None или route_steps пуст.
    """
    if effective_product_id is None or not route_steps:
        return 0.0

    route_seq_to_section: dict[int, int] = {}
    route_seq_to_op_codes: dict[int, set[str | None]] = {}
    for step in route_steps:
        seq = step.get("sequence")
        if seq is None:
            continue
        section_id = step.get("section_id")
        if section_id is not None:
            route_seq_to_section[seq] = section_id
        op_codes = step.get("operation_codes")
        route_seq_to_op_codes[seq] = set(op_codes) if op_codes else set()

    reservation_filter = SpgRemainder.reserved_for_plan_position_id.is_(None)
    if position_id is not None:
        reservation_filter = or_(
            reservation_filter,
            SpgRemainder.reserved_for_plan_position_id == position_id,
        )

    remainders: list[SpgRemainder] = (
        await db.execute(
            select(SpgRemainder)
            .where(
                SpgRemainder.product_id == effective_product_id,
                SpgRemainder.remainder_quantity > 0,
                SpgRemainder.consumed_at.is_(None),
                reservation_filter,
            )
            .order_by(SpgRemainder.created_at)
        )
    ).scalars().all()

    total = Decimal("0")
    for rem in remainders:
        stages_json: list[dict] = rem.completed_stages_json or []

        # Пустой completed_stages_json = сырьё со склада → совместимо с любым маршрутом
        is_prefix = True
        for stage_entry in stages_json:
            seq = stage_entry.get("sequence")
            section_id = stage_entry.get("section_id")
            op_code = stage_entry.get("operation_code")
            if seq is None or section_id is None:
                is_prefix = False
                break
            expected_section = route_seq_to_section.get(seq)
            if expected_section is None or expected_section != section_id:
                is_prefix = False
                break
            allowed_ops = route_seq_to_op_codes.get(seq, set())
            if allowed_ops and op_code not in allowed_ops:
                is_prefix = False
                break

        if is_prefix:
            total += rem.remainder_quantity

    return float(total)
