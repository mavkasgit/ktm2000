"""Re-export of transfer-related ORM models.

The tables themselves live in ``app.models.transfer`` and
``app.models.defect`` (the ``TransferDiscrepancyDefectItem`` join table
sits there historically).  They are re-exported here so that downstream
imports can use a single namespace:

    from app.transfers.models import Transfer, TransferStatus, TransferDiscrepancy
"""

from app.models.defect import TransferDiscrepancyDefectItem
from app.models.transfer import (
    Transfer,
    TransferDiscrepancy,
    TransferDiscrepancyStatus,
    TransferStatus,
)

__all__ = [
    "Transfer",
    "TransferStatus",
    "TransferDiscrepancy",
    "TransferDiscrepancyStatus",
    "TransferDiscrepancyDefectItem",
]
