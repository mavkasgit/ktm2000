"""Shared helpers for stock ledger tests."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.stock import Reason, StockCommand, StockCommandService


async def record_transfer_receive(
    session: AsyncSession,
    *,
    product_id: int,
    from_location_id: int,
    to_location_id: int,
    quantity: Decimal,
    task_id: int,
    created_by: int,
    transfer_id: int | None = None,
) -> None:
    """Seed issued_quantity via TRANSFER_RECEIVE (auto-issue on receive)."""
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity=quantity,
            reason=Reason.TRANSFER_RECEIVE,
            task_id=task_id,
            transfer_id=transfer_id,
            created_by=created_by,
        ),
    )