"""Read services for the transfer module.

The bodies of ``get_transfer_details`` and
``get_section_incoming_transfers`` are moved from the historical
``app.services.shopfloor.queries_details`` and
``app.services.shopfloor.queries_sections`` — no behaviour change.

The new ``list_ready_to_transfer`` query surfaces SectionTasks that
have quantity ready to be sent to the next route step, with the
auto-resolved next-section info.  This is the data source for the
dedicated ``/transfers`` UI page.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.defect import DefectItem, TransferDiscrepancyDefectItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product
from app.models.route import RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import SpgSection
from app.models.transfer import (
    Transfer,
    TransferDiscrepancy,
    TransferStatus,
)
from app.models.work_task import WorkTask, WorkTaskStatus

from app.services.shopfloor.common import _get_transfer, _to_decimal


def _fmt_qty(value: Decimal | None) -> str:
    """Format a quantity Decimal for JSON: ``Decimal("100.000")`` -> ``"100"``.

    Strips trailing zeros while preserving precision for fractional
    values (``Decimal("0.500")`` -> ``"0.5"``).
    """
    if value is None:
        return "0"
    d = _to_decimal(value)
    if d == d.to_integral_value():
        return str(d.to_integral_value())
    s = format(d, "f")
    # Strip trailing zeros after the decimal point, but keep the dot
    # if there's at least one significant fractional digit.
    if "." in s:
        s = s.rstrip("0").rstrip(".")
        if not s or s == "-":
            s = "0"
    return s


async def get_transfer_details(db: AsyncSession, transfer_id: int) -> dict:
    transfer = await _get_transfer(db, transfer_id)
    discrepancies = (
        await db.execute(
            select(TransferDiscrepancy)
            .where(TransferDiscrepancy.transfer_id == transfer.id)
            .order_by(TransferDiscrepancy.id)
        )
    ).scalars().all()
    result_discrepancies = []
    for d in discrepancies:
        links = (
            await db.execute(
                select(TransferDiscrepancyDefectItem, DefectItem)
                .join(DefectItem, DefectItem.id == TransferDiscrepancyDefectItem.defect_item_id)
                .where(TransferDiscrepancyDefectItem.transfer_discrepancy_id == d.id)
            )
        ).all()
        result_discrepancies.append(
            {
                "id": d.id,
                "discrepancy_quantity": _fmt_qty(d.discrepancy_quantity),
                "resolved_quantity": _fmt_qty(d.resolved_quantity),
                "unresolved_quantity": _fmt_qty(d.unresolved_quantity),
                "status": d.status.value,
                "reason": d.reason,
                "comment": d.comment,
                "links": [
                    {
                        "id": link.id,
                        "defect_item_id": item.id,
                        "defect_id": item.defect_id,
                        "quantity": _fmt_qty(link.quantity),
                    }
                    for link, item in links
                ],
            }
        )
    return {
        "id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "status": transfer.status.value,
        "from_task_id": transfer.from_task_id,
        "to_task_id": transfer.to_task_id,
        "sent_quantity": _fmt_qty(transfer.sent_quantity),
        "accepted_quantity": _fmt_qty(transfer.accepted_quantity) if transfer.accepted_quantity is not None else None,
        "rejected_quantity": _fmt_qty(transfer.rejected_quantity) if transfer.rejected_quantity is not None else None,
        "discrepancies": result_discrepancies,
    }


async def get_section_incoming_transfers(
    db: AsyncSession,
    *,
    section_id: int,
) -> dict:
    """Return incoming open transfers for a section."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_stage = aliased(RouteStage)
    to_stage = aliased(RouteStage)
    from_line = aliased(SectionPlanLine)

    rows = (
        await db.execute(
            select(
                Transfer,
                from_section,
                to_section,
                from_task,
                to_task,
                from_stage,
                to_stage,
                from_line,
                Product.sku,
            )
            .join(from_section, from_section.id == Transfer.from_section_id)
            .join(to_section, to_section.id == Transfer.to_section_id)
            .join(from_task, from_task.id == Transfer.from_task_id)
            .join(to_task, to_task.id == Transfer.to_task_id)
            .join(from_stage, from_stage.id == from_task.route_stage_id)
            .join(to_stage, to_stage.id == to_task.route_stage_id)
            .join(from_line, from_line.id == from_task.section_plan_line_id)
            .join(Product, Product.id == from_task.product_id)
            .where(
                Transfer.to_section_id == section_id,
                Transfer.status.in_([TransferStatus.sent, TransferStatus.partially_accepted]),
            )
            .order_by(Transfer.sent_at.desc().nullslast(), Transfer.id.desc())
        )
    ).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_stage, dst_stage, src_line, product_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal("0")

        from_op_name = ", ".join(op.operation_name for op in src_stage.operations) if src_stage and src_stage.operations else ""
        to_op_name = ", ".join(op.operation_name for op in dst_stage.operations) if dst_stage and dst_stage.operations else ""

        transfers.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status.value,
                "from_task_id": transfer.from_task_id,
                "to_task_id": transfer.to_task_id,
                "from_section_id": transfer.from_section_id,
                "from_section_code": from_sec.code,
                "from_section_name": from_sec.name,
                "to_section_id": transfer.to_section_id,
                "to_section_code": to_sec.code,
                "to_section_name": to_sec.name,
                "from_operation_name": from_op_name,
                "to_operation_name": to_op_name,
                "sent_quantity": _fmt_qty(sent),
                "accepted_quantity": _fmt_qty(accepted),
                "rejected_quantity": _fmt_qty(rejected),
                "remaining_quantity": _fmt_qty(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "is_post_factum": transfer.is_post_factum,
                "physical_handover_at": transfer.physical_handover_at.isoformat() if transfer.physical_handover_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
                "product_sku": product_sku,
                "from_line_id": src_line.id,
                "from_line_sequence": src_line.sequence,
                "plan_position_id": src_line.plan_position_id,
            }
        )

    return {
        "section_id": section_id,
        "incoming_transfers": transfers,
    }


async def list_ready_to_transfer(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    spg_id: int | None = None,
) -> dict:
    """List SectionTasks that have quantity ready to be transferred.

    A task is "ready to transfer" when:
      * it has a next route step (``SectionPlanLine.sequence + 1``
        exists),
      * the next step is not final,
      * ``cached_completed - cached_transferred > 0``.

    Filters:
      * ``section_id`` — restrict to a single section.
      * ``spg_id`` — restrict to all sections of an SPG (overrides
        ``section_id`` if both given).
    """
    from_section = aliased(Section, name="from_section")
    next_section = aliased(Section, name="next_section")
    from_stage = aliased(RouteStage, name="from_stage")
    next_stage = aliased(RouteStage, name="next_stage")
    from_line = aliased(SectionPlanLine, name="from_line")
    next_line = aliased(SectionPlanLine, name="next_line")

    from app.models.movement import Movement, MovementType

    query = (
        select(
            WorkTask,
            from_line,
            from_stage,
            from_section,
            Product.sku,
            next_line,
            next_stage,
            next_section,
            Movement.comment.label("completion_comment"),
        )
        .join(from_line, from_line.id == WorkTask.section_plan_line_id)
        .join(from_stage, from_stage.id == WorkTask.route_stage_id)
        .join(from_section, from_section.id == WorkTask.section_id)
        .join(Product, Product.id == WorkTask.product_id)
        .outerjoin(
            next_line,
            (next_line.plan_position_id == from_line.plan_position_id)
            & (next_line.sequence == from_line.sequence + 1),
        )
        .outerjoin(next_stage, next_stage.id == next_line.route_stage_id)
        .outerjoin(next_section, next_section.id == next_line.section_id)
        .outerjoin(
            Movement,
            (Movement.task_id == WorkTask.id)
            & (Movement.movement_type == MovementType.complete)
        )
        .where(
            WorkTask.status.notin_(
                [WorkTaskStatus.cancelled, WorkTaskStatus.waiting_previous]
            )
        )
    )

    if spg_id is not None:
        spg_section_ids = (
            await db.execute(
                select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
            )
        ).scalars().all()
        if not spg_section_ids:
            return {"items": [], "filters": {"section_id": section_id, "spg_id": spg_id}}
        query = query.where(WorkTask.section_id.in_(spg_section_ids))
    elif section_id is not None:
        query = query.where(WorkTask.section_id == section_id)

    query = query.order_by(from_line.sequence, WorkTask.id)
    rows = (await db.execute(query)).all()

    items: list[dict] = []
    for (
        task,
        line,
        stage,
        section,
        product_sku,
        next_l,
        next_stg,
        next_sec,
        completion_comment,
    ) in rows:
        completed = _to_decimal(task.cached_completed_quantity or 0)
        transferred = _to_decimal(task.cached_transferred_quantity or 0)
        transferable = completed - transferred
        if transferable <= 0:
            continue

        shares_spg = False
        if next_l is not None:
            from app.services.shopfloor.common import sections_share_spg
            shares_spg = await sections_share_spg(db, line.section_id, next_l.section_id)

        if shares_spg:
            continue

        has_next = next_l is not None and next_stg is not None and not bool(next_stg.is_final)
        is_final_step = bool(stage.is_final)
        # Final step tasks should never appear in "ready to transfer" — they
        # need ``final_release`` instead.
        if is_final_step:
            continue

        op_code = stage.operations[0].operation_code if stage and stage.operations else None
        op_name = ", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else ""
        next_op_name = ", ".join(op.operation_name for op in next_stg.operations) if next_stg and next_stg.operations else None

        items.append(
            {
                "task_id": task.id,
                "section_id": task.section_id,
                "section_code": section.code,
                "section_name": section.name,
                "plan_position_id": line.plan_position_id,
                "route_stage_id": stage.id,
                "sequence": stage.sequence,
                "operation_code": op_code,
                "operation_name": op_name,
                "product_id": task.product_id,
                "product_sku": product_sku,
                "planned_quantity": _fmt_qty(task.planned_quantity),
                "completed_quantity": _fmt_qty(completed),
                "already_transferred_quantity": _fmt_qty(transferred),
                "transferable_quantity": _fmt_qty(transferable),
                "has_next_step": has_next,
                "next_section_id": next_sec.id if next_sec is not None else None,
                "next_section_code": next_sec.code if next_sec is not None else None,
                "next_section_name": next_sec.name if next_sec is not None else None,
                "next_operation_name": next_op_name,
                "next_step_sequence": next_stg.sequence if next_stg is not None else None,
                "next_step_is_final": bool(next_stg.is_final) if next_stg is not None else None,
                "is_final": False,
                "completion_comment": completion_comment,
            }
        )

    return {"items": items, "filters": {"section_id": section_id, "spg_id": spg_id}}


async def get_section_transfer_history(
    db: AsyncSession,
    *,
    section_id: int | None = None,
    spg_id: int | None = None,
    limit: int = 100,
) -> dict:
    """Return both incoming and outgoing transfers for a section or SPG (history log)."""
    from_section = aliased(Section)
    to_section = aliased(Section)
    from_task = aliased(WorkTask)
    to_task = aliased(WorkTask)
    from_stage = aliased(RouteStage)
    to_stage = aliased(RouteStage)
    from_line = aliased(SectionPlanLine)

    base_query = (
        select(
            Transfer,
            from_section,
            to_section,
            from_task,
            to_task,
            from_stage,
            to_stage,
            from_line,
            Product.sku,
        )
        .join(from_section, from_section.id == Transfer.from_section_id)
        .join(to_section, to_section.id == Transfer.to_section_id)
        .join(from_task, from_task.id == Transfer.from_task_id)
        .join(to_task, to_task.id == Transfer.to_task_id)
        .join(from_stage, from_stage.id == from_task.route_stage_id)
        .join(to_stage, to_stage.id == to_task.route_stage_id)
        .join(from_line, from_line.id == from_task.section_plan_line_id)
        .join(Product, Product.id == from_task.product_id)
    )

    if spg_id is not None:
        from app.models.spg import SpgSection
        spg_section_ids = (
            await db.execute(
                select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
            )
        ).scalars().all()
        if not spg_section_ids:
            return {"section_id": None, "spg_id": spg_id, "transfers": []}
        base_query = base_query.where(
            (Transfer.from_section_id.in_(spg_section_ids)) | (Transfer.to_section_id.in_(spg_section_ids))
        )
    elif section_id is not None:
        base_query = base_query.where(
            (Transfer.from_section_id == section_id) | (Transfer.to_section_id == section_id)
        )

    rows = (
        await db.execute(
            base_query
            .order_by(Transfer.created_at.desc(), Transfer.id.desc())
            .limit(limit)
        )
    ).all()

    transfers = []
    for transfer, from_sec, to_sec, src_task, dst_task, src_stage, dst_stage, src_line, product_sku in rows:
        sent = _to_decimal(transfer.sent_quantity or 0)
        accepted = _to_decimal(transfer.accepted_quantity or 0)
        rejected = _to_decimal(transfer.rejected_quantity or 0)
        remaining = sent - accepted - rejected
        if remaining < 0:
            remaining = Decimal("0")

        from_op_name = ", ".join(op.operation_name for op in src_stage.operations) if src_stage and src_stage.operations else ""
        to_op_name = ", ".join(op.operation_name for op in dst_stage.operations) if dst_stage and dst_stage.operations else ""

        transfers.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status.value,
                "from_task_id": transfer.from_task_id,
                "to_task_id": transfer.to_task_id,
                "from_section_id": transfer.from_section_id,
                "from_section_code": from_sec.code,
                "from_section_name": from_sec.name,
                "to_section_id": transfer.to_section_id,
                "to_section_code": to_sec.code,
                "to_section_name": to_sec.name,
                "from_operation_name": from_op_name,
                "to_operation_name": to_op_name,
                "sent_quantity": _fmt_qty(sent),
                "accepted_quantity": _fmt_qty(accepted),
                "rejected_quantity": _fmt_qty(rejected),
                "remaining_quantity": _fmt_qty(remaining),
                "comment": transfer.comment,
                "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
                "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
                "is_post_factum": transfer.is_post_factum,
                "physical_handover_at": transfer.physical_handover_at.isoformat() if transfer.physical_handover_at else None,
                "from_task_status": src_task.status.value,
                "to_task_status": dst_task.status.value,
                "product_sku": product_sku,
                "from_line_id": src_line.id,
                "from_line_sequence": src_line.sequence,
                "plan_position_id": src_line.plan_position_id,
            }
        )

    return {
        "section_id": section_id,
        "spg_id": spg_id,
        "transfers": transfers,
    }

