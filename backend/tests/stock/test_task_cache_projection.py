from decimal import Decimal

from app.stock.task_cache import (
    compute_task_available,
    effective_issued_quantity,
    resolve_work_task_status,
)


def test_effective_issued_equals_received_transfer():
    assert effective_issued_quantity(received=Decimal("100")) == Decimal("100")


def test_effective_issued_zero_when_not_received():
    assert effective_issued_quantity(received=Decimal("0")) == Decimal("0")


def test_effective_issued_ignores_legacy_issue_to_work_channel():
    """issued = received only; legacy ISSUE_TO_WORK rows are not summed."""
    assert effective_issued_quantity(received=Decimal("100")) == Decimal("100")


def test_resolve_work_task_status_completes_when_fully_transferred():
    assert resolve_work_task_status(
        current_status="ready",
        planned_quantity=Decimal("1008"),
        remaining_quantity=Decimal("0"),
        transferred_quantity=Decimal("1008"),
        completed_quantity=Decimal("1008"),
        rejected_quantity=Decimal("0"),
        issued_quantity=Decimal("1008"),
        received_quantity=Decimal("1008"),
    ) == "completed"


def test_resolve_work_task_status_partial_when_remainder_left():
    assert resolve_work_task_status(
        current_status="ready",
        planned_quantity=Decimal("100"),
        remaining_quantity=Decimal("50"),
        transferred_quantity=Decimal("50"),
        completed_quantity=Decimal("50"),
        rejected_quantity=Decimal("0"),
        issued_quantity=Decimal("100"),
        received_quantity=Decimal("100"),
    ) == "partially_completed"


def test_available_after_transfer_receive_on_second_stage():
    available = compute_task_available(
        planned_quantity=Decimal("504"),
        received_quantity=Decimal("504"),
        issued_quantity=effective_issued_quantity(received=Decimal("504")),
        returned_quantity=Decimal("0"),
        is_first_stage=False,
    )
    assert available == Decimal("0")