"""Transfer module — explicit transfer process between SPGs.

The transfer module is responsible for moving completed quantity from one
SPG (or section) to the next, according to the route attached to a
SectionTask.  It is a SEPARATE process from SectionTask completion:

  * ``complete_task`` only updates the local section's ledger and
    decrements availability.
  * Once a SectionTask is ``completed``, the operator (or another
    process) explicitly creates a ``Transfer`` that moves quantity to
    the next route step, which is handled here.

Under the explicit-transfer model, ``transfer_send`` is the single write
path: it creates the ``Transfer`` row, both ledger Movements
(``transfer_send`` + ``transfer_receive``) and flips the destination
``WorkTask`` to ``ready``. There is no separate manual accept step.

Public surface:
  * ``services`` — write operations (``transfer_send``; ``transfer_receive``
    and ``resolve_transfer_discrepancy_link`` are kept as legacy no-ops
    for the few call sites that haven't migrated)
  * ``queries``  — read operations (details, incoming, ready-to-transfer)
  * ``schemas``  — Pydantic DTOs for the FastAPI router
  * ``api``      — FastAPI router mounted under ``/transfers``

The DB schema lives in ``app.models.transfer`` (no schema migration
required for this refactor).  Compatibility with the old
``/shopfloor/transfers`` endpoints is preserved by thin proxies in
``app.api.routes.shopfloor``.
"""

from app.transfers.queries import (
    get_section_incoming_transfers,
    get_transfer_details,
    list_ready_to_transfer,
)
from app.transfers.services import (
    cancel_transfer,
    correct_transfer,
    resolve_transfer_discrepancy_link,
    transfer_receive,
    transfer_send,
)

__all__ = [
    "transfer_send",
    "transfer_receive",
    "cancel_transfer",
    "correct_transfer",
    "resolve_transfer_discrepancy_link",
    "get_transfer_details",
    "get_section_incoming_transfers",
    "list_ready_to_transfer",
]
