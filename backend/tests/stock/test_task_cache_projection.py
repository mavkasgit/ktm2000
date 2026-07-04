from decimal import Decimal

from app.stock.task_cache import (
    compute_task_available,
    effective_issued_quantity,
)


def test_effective_issued_equals_received_transfer():
    assert effective_issued_quantity(received=Decimal("100")) == Decimal("100")


def test_effective_issued_zero_when_not_received():
    assert effective_issued_quantity(received=Decimal("0")) == Decimal("0")


def test_effective_issued_ignores_legacy_issue_to_work_channel():
    """issued = received only; legacy ISSUE_TO_WORK rows are not summed."""
    assert effective_issued_quantity(received=Decimal("100")) == Decimal("100")


def test_available_after_transfer_receive_on_second_stage():
    available = compute_task_available(
        planned_quantity=Decimal("504"),
        received_quantity=Decimal("504"),
        issued_quantity=effective_issued_quantity(received=Decimal("504")),
        returned_quantity=Decimal("0"),
        is_first_stage=False,
    )
    assert available == Decimal("0")