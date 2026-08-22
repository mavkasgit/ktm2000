"""REST ресурс /actions — ядро Reversal (ADR-0019, тикет #114, D6).

  * GET  /actions/{id}/tree            → ActionTree
  * POST /actions/{id}/preview-reverse {cascade} → ReversalPreview + plan_token
  * POST /actions/{id}/reverse {plan_token, reason?} → ReversalResult

Ошибки: AlreadyReversed → 409; HasDependentActions/CoverageShortfall →
409 с payload-подсказкой; StalePlanToken → 409 «пересмотрите preview»;
NotAllowed → 403.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.reversal import errors
from app.reversal.schemas import (
    ActionNodeOut,
    BlockerOut,
    PreviewIn,
    PreviewOut,
    ReverseIn,
    ReverseResultOut,
    TreeNodeOut,
    TreeOut,
)
from app.reversal.service import reversal_service

router = APIRouter(prefix="/actions", tags=["reversal"])


def _node_out(node) -> ActionNodeOut:
    return ActionNodeOut(
        id=node.id,
        action_type=node.action_type,
        ref_id=node.ref_id,
        status=node.status,
        depends_on=list(node.depends_on),
    )


def _blocker_out(b) -> BlockerOut:
    return BlockerOut(
        code=b.code,
        node_id=b.node_id,
        detail=b.detail,
        deficit=str(b.deficit) if b.deficit is not None else None,
        chain=list(b.chain) if b.chain is not None else None,
    )


@router.get(
    "/{action_id}/tree",
    response_model=TreeOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def get_action_tree(action_id: int, db: AsyncSession = Depends(get_db)) -> TreeOut:
    try:
        tree = await reversal_service.tree(db, action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def to_out(n) -> TreeNodeOut:
        return TreeNodeOut(
            id=n.id,
            action_type=n.action_type,
            ref_id=n.ref_id,
            status=n.status,
            depends_on=list(n.depends_on),
            children=[to_out(c) for c in n.children],
        )

    return TreeOut(root=to_out(tree.root), total_nodes=tree.total_nodes)


@router.post(
    "/{action_id}/preview-reverse",
    response_model=PreviewOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def preview_reverse(
    action_id: int,
    payload: PreviewIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> PreviewOut:
    cascade = bool(payload and payload.cascade)
    try:
        preview = await reversal_service.preview_reverse(db, action_id, cascade=cascade)
    except errors.AlreadyReversed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PreviewOut(
        action_id=preview.action_id,
        cascade=preview.cascade,
        revert=[_node_out(n) for n in preview.revert],
        stays=[_node_out(n) for n in preview.stays],
        blockers=[_blocker_out(b) for b in preview.blockers],
        plan_token=preview.plan_token,
    )


@router.post(
    "/{action_id}/reverse",
    response_model=ReverseResultOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def reverse_action(
    action_id: int,
    payload: ReverseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReverseResultOut:
    try:
        result = await reversal_service.reverse(
            db,
            action_id,
            plan_token=payload.plan_token,
            reason=payload.reason,
            actor=getattr(current_user, "full_name", None) or "system",
            actor_id=getattr(current_user, "id", None),
        )
    except errors.AlreadyReversed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except errors.HasDependentActions as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": str(exc), "chain": exc.chain},
        ) from exc
    except errors.CoverageShortfall as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": str(exc), "node": exc.node, "deficit": str(exc.deficit)},
        ) from exc
    except errors.StalePlanToken as exc:
        raise HTTPException(
            status_code=409,
            detail="Мир изменился с момента preview — пересмотрите preview",
        ) from exc
    except errors.NotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReverseResultOut(
        action_id=result.action_id,
        reversal_action_id=result.reversal_action_id,
        reversed_action_ids=list(result.reversed_action_ids),
        compensated_tx_ids=list(result.compensated_tx_ids),
    )
