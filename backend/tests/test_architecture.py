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
    """P7: номер передачи — метка UTC до микросекунд с уникальным индексом.

    Дёшевая DB-free проверка факта из NIGHT_REPORT.md §7:суффикс к номеру
    меняет формат — продуктовое решение владельца, а не ночная правка.
    """
    import re
    from datetime import UTC, datetime

    from app.models.transfer import Transfer
    from app.services.shopfloor.common import _transfer_no

    numbers = [_transfer_no() for _ in range(200)]
    assert len(set(numbers)) == len(numbers)
    assert all(re.fullmatch(r"TR-\d{20}", number) for number in numbers)
    datetime.strptime(numbers[0][len("TR-") :], "%Y%m%d%H%M%S%f").replace(tzinfo=UTC)
    # create_all in tests builds the schema without alembic — the model must
    # carry the same guarantee as migration 007 (uq_transfers_transfer_no).
    assert Transfer.__table__.c.transfer_no.unique is True


def test_test_runner_and_db_cli_share_admin_env_names() -> None:
    """P7: launcher и CLI используют одни имена admin-переменных окружения."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "test-run.ps1").read_text(encoding="utf-8")
    cli = (root / "scripts" / "test-db.py").read_text(encoding="utf-8")

    for name in ("TEST_DB_ADMIN_USER", "TEST_DB_ADMIN_PASSWORD"):
        assert name in cli, f"{name} missing in test-db.py"
        assert name in runner, f"{name} missing in test-run.ps1"
    # Legacy names remain fallbacks and are propagated to the child process,
    # so overriding only them cannot split the DSN from the DB lifecycle.
    assert "$env:TEST_DB_USER" in runner
    assert "$env:TEST_DB_PASSWORD" in runner
    assert "$env:TEST_DB_ADMIN_USER = $env:TEST_DB_USER" in runner
    assert "$env:TEST_DB_ADMIN_PASSWORD = $env:TEST_DB_PASSWORD" in runner
