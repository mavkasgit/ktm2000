"""Pydantic-схемы REST ресурса /actions (D6, тикет #114)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PreviewIn(BaseModel):
    cascade: bool = False


class ReverseIn(BaseModel):
    plan_token: str
    reason: str | None = None


class PreviewAmendIn(BaseModel):
    """Изменения домена (валидует компенсатор) + флаг каскада."""

    changes: dict
    cascade: bool = False


class AmendIn(BaseModel):
    plan_token: str  # изменения уже подписаны в токене preview_amend
    reason: str | None = None

class ActionNodeOut(BaseModel):
    id: int
    action_type: str
    ref_id: int | None = None
    status: str
    depends_on: list[int] = Field(default_factory=list)


class TreeNodeOut(ActionNodeOut):
    children: list["TreeNodeOut"] = Field(default_factory=list)


class TreeOut(BaseModel):
    root: TreeNodeOut
    total_nodes: int


class BlockerOut(BaseModel):
    kind: str
    node_id: int | None = None
    detail: str
    deficit: str | None = None
    chain: list[int] | None = None


class WillReplayOut(BaseModel):
    """Узел плана реплея (#121): order — позиция в прямом топологическом."""

    action_id: int
    champion_id: int
    action_type: str
    ref_id: int | None = None
    order: int


class PreviewOut(BaseModel):
    """Три зоны: revert 🔴 / stays ⚪ / blockers 🚫 + plan_token."""

    action_id: int
    cascade: bool
    revert: list[ActionNodeOut]
    stays: list[ActionNodeOut]
    blockers: list[BlockerOut]
    plan_token: str | None = None  # None при блокировках
    will_replay: list[WillReplayOut] = Field(default_factory=list)  # план реплея (#121)


class ActionOut(BaseModel):
    """Строка журнала действий (list-endpoint, тикет #117)."""

    id: int
    action_type: str
    ref_id: int | None = None
    actor: str | None = None
    status: str
    depends_on: list[int] = Field(default_factory=list)
    created_at: str | None = None


class ActionsListOut(BaseModel):
    items: list[ActionOut]
    total: int
    page: int
    page_size: int


class ReverseResultOut(BaseModel):
    action_id: int
    reversal_action_id: int
    reversed_action_ids: list[int]
    compensated_tx_ids: list[int]


class HardPurgeIn(BaseModel):
    """dry_run=True → отчёт + plan_token kind='purge'; False → confirm (#118)."""

    dry_run: bool = True
    plan_token: str | None = None


class PurgePairOut(BaseModel):
    source_tx_id: int
    reverse_tx_id: int
    product_id: int
    quantity: str


class HardPurgeOut(BaseModel):
    """Отчёт hard-purge: пары «исходная+компенсация» + итог."""

    action_id: int
    total_pairs: int
    pairs: list[PurgePairOut]
    plan_token: str | None = None  # только dry_run
    deleted_tx_ids: list[int] = Field(default_factory=list)  # после confirm


class AmendResultOut(BaseModel):
    action_id: int
    new_action_id: int
    new_ref_id: int | None = None
    compensated_tx_ids: list[int]
    amended_action_ids: list[int]
    reversed_action_ids: list[int]
    replayed_action_ids: list[int] = Field(default_factory=list)  # #121


TreeNodeOut.model_rebuild()
