"""REST ресурс /actions — ядро Reversal (ADR-0019, тикет #114, D6).

  * GET  /actions/{id}/tree            → ActionTree
  * POST /actions/{id}/preview-reverse {cascade} → ReversalPreview + plan_token
  * POST /actions/{id}/reverse {plan_token, reason?} → ReversalResult
  * POST /actions/{id}/preview-amend {changes, cascade} → Preview + plan_token
  * POST /actions/{id}/amend {plan_token, reason?} → AmendResult   (#115)
  * POST /actions/{id}/hard-purge {dry_run, plan_token?} → HardPurgeOut (#118, admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.action_journal import Action, ActionStatus
from app.reversal import errors
from app.reversal.schemas import (
    ActionNodeOut,
    AmendIn,
    AmendResultOut,
    BlockerOut,
    PreviewAmendIn,
    PreviewIn,
    ActionOut,
    ActionsListOut,
    PreviewOut,
    ReverseIn,
    ReverseResultOut,
    HardPurgeIn,
    HardPurgeOut,
    PurgePairOut,
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
        kind=b.kind,
        node_id=b.node_id,
        detail=b.detail,
        deficit=str(b.deficit) if b.deficit is not None else None,
        chain=list(b.chain) if b.chain is not None else None,
    )


@router.get(
    "",
    response_model=ActionsListOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def list_actions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    action_type: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ActionsListOut:
    """Список журнала действий (тикет #117): пагинация page/page_size,
    фильтры action_type/status."""
    stmt = select(Action)
    count_stmt = select(func.count()).select_from(Action)
    if action_type:
        stmt = stmt.where(Action.action_type == action_type)
        count_stmt = count_stmt.where(Action.action_type == action_type)
    if status:
        try:
            status_value = ActionStatus(status)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Неизвестный статус: {status}"
            ) from exc
        stmt = stmt.where(Action.status == status_value)
        count_stmt = count_stmt.where(Action.status == status_value)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Action.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ActionsListOut(
        items=[
            ActionOut(
                id=row.id,
                action_type=row.action_type,
                ref_id=row.ref_id,
                actor=row.actor,
                status=row.status.value if hasattr(row.status, "value") else str(row.status),
                depends_on=list(row.depends_on or []),
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
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


@router.post(
    "/{action_id}/preview-amend",
    response_model=PreviewOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def preview_amend(
    action_id: int,
    payload: PreviewAmendIn,
    db: AsyncSession = Depends(get_db),
) -> PreviewOut:
    try:
        preview = await reversal_service.preview_amend(
            db, action_id, dict(payload.changes), cascade=payload.cascade
        )
    except errors.AlreadyReversed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except errors.NotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    "/{action_id}/amend",
    response_model=AmendResultOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def amend_action(
    action_id: int,
    payload: AmendIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AmendResultOut:
    try:
        changes = reversal_service.amend_changes_from_token(payload.plan_token)
        result = await reversal_service.amend(
            db,
            action_id,
            changes=changes,
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
            detail="Мир изменился с момента preview — пересмотрите preview-amend",
        ) from exc
    except errors.NotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AmendResultOut(
        action_id=result.action_id,
        new_action_id=result.new_action_id,
        new_ref_id=result.new_ref_id,
        compensated_tx_ids=list(result.compensated_tx_ids),
        amended_action_ids=list(result.amended_action_ids),
        reversed_action_ids=list(result.reversed_action_ids),
    )


@router.post(
    "/{action_id}/hard-purge",
    response_model=HardPurgeOut,
    dependencies=[Depends(require_role([UserRole.admin]))],  # отдельное право (ADR-0019 п.7)
)
async def hard_purge_action(
    action_id: int,
    payload: HardPurgeIn,
    db: AsyncSession = Depends(get_db),
) -> HardPurgeOut:
    """Hard-чистка скомпенсированного действия (#118): dry_run → отчёт +
    plan_token; confirm — физическое удаление пар и статус 'purged'."""
    try:
        result = await reversal_service.hard_purge(
            db,
            action_id,
            dry_run=payload.dry_run,
            plan_token=payload.plan_token,
        )
    except errors.StalePlanToken as exc:
        raise HTTPException(
            status_code=409,
            detail="Мир изменился с момента dry_run — повторите hard-purge",
        ) from exc
    except errors.NotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HardPurgeOut(
        action_id=result.action_id,
        total_pairs=len(result.pairs),
        pairs=[
            PurgePairOut(
                source_tx_id=p.source_tx_id,
                reverse_tx_id=p.reverse_tx_id,
                product_id=p.product_id,
                quantity=str(p.quantity),
            )
            for p in result.pairs
        ],
        plan_token=result.plan_token,
        deleted_tx_ids=list(result.deleted_tx_ids),
    )
