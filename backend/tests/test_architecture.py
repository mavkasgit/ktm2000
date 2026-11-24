"""Architectural regression guards — DB-free, fast.

Protects the decision «legacy transfer scaffold must not come back»:
shim modules, no-op functions and dead DTOs that were removed in the
transfer cleanup are asserted absent. Runs without any DB fixture so it
is safe under pytest-xdist.
"""

import importlib.util

from app.transfers import schemas, services


def test_transfer_shim_modules_removed() -> None:
    for module_name in (
        "app.services.shopfloor.operations_transfers",
        "app.transfers.models",
    ):
        assert importlib.util.find_spec(module_name) is None, (
            f"Legacy shim module '{module_name}' must not exist"
        )


def test_transfer_noop_functions_removed() -> None:
    for symbol in ("transfer_receive", "resolve_transfer_discrepancy_link"):
        assert not hasattr(services, symbol), (
            f"Legacy no-op '{symbol}' must not be exported from app.transfers.services"
        )


def test_transfer_dead_dtos_removed() -> None:
    for symbol in (
        "AcceptTransferPayload",
        "ResolveDiscrepancyPayload",
        "TransferOut",
        "ReadyToTransferTaskOut",
    ):
        assert not hasattr(schemas, symbol), (
            f"Dead DTO '{symbol}' must not be defined in app.transfers.schemas"
        )


def test_transfer_barrel_is_empty() -> None:
    import app.transfers as transfers_pkg

    assert getattr(transfers_pkg, "__all__", None) is None
    assert not hasattr(transfers_pkg, "transfer_send")
    assert not hasattr(transfers_pkg, "transfer_receive")


def test_dead_lock_helper_removed() -> None:
    from app.api import deps

    assert not hasattr(deps, "_ensure_transfer_target_lock")


def test_transfer_no_format_and_unique_index() -> None:
    """P7: номер передачи — UTC-метка до микросекунд, уникальность держит индекс.

    Формат суффикса — продуктовое решение владельца (NIGHT_REPORT.md §7),
    поэтому проверяется только текущий контракт и индекс миграции 007.
    """
    import re

    from app.models.transfer import Transfer
    from app.services.shopfloor.common import _transfer_no

    assert re.fullmatch(r"TR-\d{20}", _transfer_no())
    # create_all в тестах строит схему без alembic — модель обязана нести
    # ту же гарантию, что миграция 007 (uq_transfers_transfer_no).
    assert Transfer.__table__.c.transfer_no.unique is True
