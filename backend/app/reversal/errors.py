"""Типизированные ошибки Reversal (ADR-0019 п.8)."""
from __future__ import annotations

from decimal import Decimal


class ReversalError(Exception):
    """Базовая ошибка механизма отката."""


class AlreadyReversed(ReversalError):
    def __init__(self, action_id: int) -> None:
        self.action_id = action_id
        super().__init__(f"Action #{action_id} уже отменён")


class HasDependentActions(ReversalError):
    """Есть активные действия, зависящие от данного (chain)."""

    def __init__(self, chain: list[int]) -> None:
        self.chain = chain
        super().__init__(
            "Есть зависимые действия, которые нужно отменить первыми: "
            + ", ".join(f"#{i}" for i in chain)
        )


class CoverageShortfall(ReversalError):
    """Не хватает покрытия хвоста цепочки для отката узла."""

    def __init__(self, node: int, deficit: Decimal) -> None:
        self.node = node
        self.deficit = deficit
        super().__init__(
            f"Недостаточно покрытия для отката действия #{node}: "
            f"дефицит {deficit}"
        )


class StalePlanToken(ReversalError):
    """Мир изменился между preview и confirm — пересмотрите preview."""


class NotAllowed(ReversalError):
    """Откат данного типа действий не поддерживается / запрещён."""
