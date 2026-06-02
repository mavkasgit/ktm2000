"""Deprecated compatibility shim.

The transfer write services have been moved to
:mod:`app.transfers.services`.  This module re-exports the same symbols
so that historical ``from app.services.shopfloor.operations_transfers
import transfer_send`` (and friends) keep working until the legacy
imports are migrated.

New code MUST import from ``app.transfers.services`` directly.
"""

from app.transfers.services import (
    resolve_transfer_discrepancy_link,
    transfer_receive,
    transfer_send,
)

__all__ = [
    "transfer_send",
    "transfer_receive",
    "resolve_transfer_discrepancy_link",
]
