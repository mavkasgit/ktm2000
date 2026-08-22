"""Ядро Reversal (ADR-0019, эпик #112, тикет #114).

* ``base`` — контракт Compensator и структуры плана/результата;
* ``errors`` — типизированные ошибки отката;
* ``stock_compensator`` — компенсатор стоковых действий;
* ``service`` — ReversalService: tree / preview_reverse / reverse.
"""
from app.reversal.base import (
    Compensator,
    PlannedEntry,
    ReversalCheck,
    ReversalPlan,
    ReversalResult,
)
from app.reversal.errors import (
    AlreadyReversed,
    CoverageShortfall,
    HasDependentActions,
    NotAllowed,
    StalePlanToken,
)

__all__ = [
    "Compensator",
    "PlannedEntry",
    "ReversalCheck",
    "ReversalPlan",
    "ReversalResult",
    "AlreadyReversed",
    "CoverageShortfall",
    "HasDependentActions",
    "NotAllowed",
    "StalePlanToken",
]
