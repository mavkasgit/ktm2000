"""Pydantic-схемы REST ресурса /actions (D6, тикет #114)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PreviewIn(BaseModel):
    cascade: bool = False


class ReverseIn(BaseModel):
    plan_token: str
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


class PreviewOut(BaseModel):
    """Три зоны: revert 🔴 / stays ⚪ / blockers 🚫 + plan_token."""

    action_id: int
    cascade: bool
    revert: list[ActionNodeOut]
    stays: list[ActionNodeOut]
    blockers: list[BlockerOut]
    plan_token: str | None = None  # None при блокировках


class ReverseResultOut(BaseModel):
    action_id: int
    reversal_action_id: int
    reversed_action_ids: list[int]
    compensated_tx_ids: list[int]


TreeNodeOut.model_rebuild()
