"""Pydantic DTOs for the transfer module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class CreateTransferPayload(BaseModel):
    """Body for ``POST /transfers``.

    ``to_task_id`` is optional — when omitted, the target ``WorkTask``
    on the next route step is auto-created (status ``waiting_previous``).
    """

    from_task_id: int
    to_task_id: int | None = None
    quantity: Decimal
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None
    post_factum: bool = False
    allow_over_plan: bool = False
    physical_handover_at: datetime | None = None
    # Габарит передаваемого материала (ADR-0001), например
    # {"length_mm": 2700}; None = безразмерные штуки.
    dimensions: dict | None = None


class CorrectTransferPayload(BaseModel):
    quantity: Decimal
    comment: str | None = None

