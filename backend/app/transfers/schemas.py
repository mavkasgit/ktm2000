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


class AcceptTransferPayload(BaseModel):
    """Body for ``POST /transfers/{id}/accept``.

    ``accepted_quantity + rejected_quantity`` must be ``> 0`` and
    ``<= transfer.sent_quantity``.
    """

    accepted_quantity: Decimal = Decimal("0")
    rejected_quantity: Decimal = Decimal("0")
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None
    executor_user_id: int | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None


class ResolveDiscrepancyPayload(BaseModel):
    """Body for ``POST /transfers/{id}/discrepancies/{did}/resolve-link``."""

    defect_item_id: int
    quantity: Decimal
    comment: str | None = None


class TransferOut(BaseModel):
    """Read DTO for a single transfer (used in list responses)."""

    id: int
    transfer_no: str
    status: str
    from_task_id: int
    to_task_id: int
    from_section_id: int
    from_section_code: str | None = None
    from_section_name: str | None = None
    to_section_id: int
    to_section_code: str | None = None
    to_section_name: str | None = None
    product_id: int
    product_sku: str | None = None
    from_operation_name: str | None = None
    to_operation_name: str | None = None
    sent_quantity: str
    accepted_quantity: str | None = None
    rejected_quantity: str | None = None
    remaining_quantity: str | None = None
    comment: str | None = None
    sent_at: str | None = None
    accepted_at: str | None = None
    created_at: str | None = None
    from_line_id: int | None = None
    from_line_sequence: int | None = None
    plan_position_id: int | None = None


class ReadyToTransferTaskOut(BaseModel):
    """Read DTO for ``GET /transfers/ready``.

    Describes a ``WorkTask`` that has quantity ready to be sent to the
    next route step, with the auto-resolved next section info.
    """

    task_id: int
    section_id: int
    section_code: str | None = None
    section_name: str | None = None
    plan_position_id: int
    route_step_id: int
    sequence: int
    operation_code: str | None = None
    operation_name: str | None = None
    product_id: int
    product_sku: str | None = None
    planned_quantity: str
    completed_quantity: str
    already_transferred_quantity: str
    transferable_quantity: str
    has_next_step: bool
    next_section_id: int | None = None
    next_section_code: str | None = None
    next_section_name: str | None = None
    next_operation_name: str | None = None
    next_step_sequence: int | None = None
    next_step_is_final: bool | None = None
    is_final: bool
