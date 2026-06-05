from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.section import Section
from app.models.spg_remainder import SpgRemainder
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStage


async def get_spg_snapshot(
    db: AsyncSession,
    *,
    spg_id: int,
) -> dict:
    """Return aggregated snapshot for a Storage Production Group.

    For every product that has work_tasks in any of the SPG's sections:
      - per-section quantities (planned, completed, in_work, available)
      - warehouse remainders
      - overall completion %
    """
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        return {"error": "SPG not found"}

    # Get section IDs belonging to this SPG
    section_ids_q = select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    section_ids = (await db.execute(section_ids_q)).scalars().all()

    if not section_ids:
        return {
            "spg_id": spg.id,
            "spg_code": spg.code,
            "spg_name": spg.name,
            "sections": [],
            "rows": [],
            "totals": {"planned": 0, "completed": 0, "in_work": 0, "remainders": 0, "negative_total": 0, "negative_remainder_count": 0},
        }

    # Fetch sections info
    sections_rows = (
        await db.execute(
            select(Section).where(Section.id.in_(section_ids)).order_by(Section.sort_order)
        )
    ).scalars().all()
    sections_out = [
        {"id": s.id, "code": s.code, "name": s.name, "icon": s.icon, "icon_color": s.icon_color}
        for s in sections_rows
    ]
    section_id_to_code = {s.id: s.code for s in sections_rows}

    # Subquery: find plan positions that have already completed their final route stage task
    completed_positions_subq = (
        select(SectionPlanLine.plan_position_id)
        .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
        .where(
            WorkTask.status == WorkTaskStatus.completed,
            RouteStage.is_final.is_(True),
        )
    )

    # Aggregate work_tasks per (product_id, section_id), excluding completed/cancelled/deleted positions
    task_agg_q = (
        select(
            WorkTask.product_id,
            WorkTask.section_id,
            func.sum(WorkTask.planned_quantity).label("planned"),
            func.sum(WorkTask.cached_completed_quantity).label("completed"),
            func.sum(WorkTask.cached_in_work_quantity).label("in_work"),
            func.sum(WorkTask.cached_available_quantity).label("available"),
            func.sum(WorkTask.cached_issued_quantity).label("issued"),
            func.sum(WorkTask.cached_transferred_quantity).label("transferred"),
            func.sum(WorkTask.cached_received_quantity).label("received"),
        )
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .join(PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id)
        .where(
            WorkTask.section_id.in_(section_ids),
            PlanPosition.deleted_at.is_(None),
            PlanPosition.status != PlanPositionStatus.cancelled,
            SectionPlanLine.plan_position_id.notin_(completed_positions_subq),
        )
        .group_by(WorkTask.product_id, WorkTask.section_id)
    )
    task_rows = (await db.execute(task_agg_q)).all()

    # Aggregate spg_remainders per product_id for this SPG
    rem_agg_q = (
        select(
            SpgRemainder.product_id,
            func.sum(SpgRemainder.remainder_quantity).label("remainder_total"),
        )
        .where(
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
        .group_by(SpgRemainder.product_id)
    )
    rem_rows = (await db.execute(rem_agg_q)).all()

    # Aggregate negative remainders across all sections in this SPG
    neg_agg_q = (
        select(
            func.coalesce(
                func.sum(func.least(SpgRemainder.remainder_quantity, 0)),
                0,
            ).label("neg_total"),
            func.coalesce(
                func.sum(
                    func.cast(SpgRemainder.remainder_quantity < 0, Integer)
                ),
                0,
            ).label("neg_count"),
        )
        .where(
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
    )
    neg_row = (await db.execute(neg_agg_q)).one()
    neg_total = float(neg_row.neg_total or 0)
    neg_count = int(neg_row.neg_count or 0)

    # Per-product negative remainder count
    neg_count_per_product_q = (
        select(
            SpgRemainder.product_id,
            func.coalesce(
                func.sum(func.cast(SpgRemainder.remainder_quantity < 0, Integer)),
                0,
            ).label("neg_count"),
        )
        .where(
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
        .group_by(SpgRemainder.product_id)
    )
    neg_count_per_product_rows = (await db.execute(neg_count_per_product_q)).all()
    neg_count_per_product = {
        r.product_id: int(r.neg_count or 0) for r in neg_count_per_product_rows
    }

    # Collect all product_ids
    product_ids = {r.product_id for r in task_rows} | {r.product_id for r in rem_rows}
    if not product_ids:
        return {
            "spg_id": spg.id,
            "spg_code": spg.code,
            "spg_name": spg.name,
            "sections": sections_out,
            "rows": [],
            "totals": {"planned": 0, "completed": 0, "in_work": 0, "remainders": 0, "negative_total": 0, "negative_remainder_count": 0},
        }

    # Fetch products
    products = (
        await db.execute(select(Product).where(Product.id.in_(product_ids)))
    ).scalars().all()
    product_map = {p.id: p for p in products}

    # Build lookup dicts
    task_lookup: dict[tuple[int, int], dict] = {}
    for r in task_rows:
        task_lookup[(r.product_id, r.section_id)] = {
            "planned": float(r.planned or 0),
            "completed": float(r.completed or 0),
            "in_work": float(r.in_work or 0),
            "available": float(r.available or 0),
            "issued": float(r.issued or 0),
            "transferred": float(r.transferred or 0),
            "received": float(r.received or 0),
        }

    rem_lookup: dict[int, float] = {}
    for r in rem_rows:
        rem_lookup[r.product_id] = float(r.remainder_total or 0)

    # Build rows
    rows = []
    totals_planned = 0.0
    totals_completed = 0.0
    totals_in_work = 0.0
    totals_remainders = 0.0
    totals_issued = 0.0

    for pid in sorted(product_ids):
        product = product_map.get(pid)
        if product is None:
            continue

        per_section: dict[str, dict] = {}
        planned_total = 0.0
        completed_total = 0.0
        in_work_total = 0.0
        remainder_total = rem_lookup.get(pid, 0.0)
        issued_total = 0.0
        max_location_value = -1.0
        current_section_code: str | None = None

        first_section_code = section_id_to_code[section_ids[0]] if section_ids else None

        for sid in section_ids:
            scode = section_id_to_code[sid]
            t = task_lookup.get((pid, sid))
            rem = remainder_total if scode == first_section_code else 0.0

            if t:
                per_section[scode] = {**t, "remainder": rem}
                planned_total += t["planned"]
                completed_total += t["completed"]
                in_work_total += t["in_work"]
                issued_total += t["issued"]

                # Current section = where most material is (in_work + available)
                location_val = t["in_work"] + t["available"]
                if location_val > max_location_value:
                    max_location_value = location_val
                    current_section_code = scode
            elif rem != 0:
                per_section[scode] = {
                    "planned": 0, "completed": 0, "in_work": 0, "available": 0,
                    "issued": 0, "transferred": 0, "received": 0, "remainder": rem,
                }

        completion_pct = round(completed_total / planned_total * 100, 1) if planned_total > 0 else 0.0

        rows.append({
            "product_id": pid,
            "sku": product.sku,
            "product_name": product.name,
            "planned_total": planned_total,
            "completed_total": completed_total,
            "in_work_total": in_work_total,
            "issued_total": issued_total,
            "remainder_total": remainder_total,
            "spg_available": remainder_total,
            "completion_pct": completion_pct,
            "current_section": current_section_code,
            "negative_remainder_count": neg_count_per_product.get(pid, 0),
            "per_section": per_section,
        })

        totals_planned += planned_total
        totals_completed += completed_total
        totals_in_work += in_work_total
        totals_remainders += remainder_total
        totals_issued += issued_total

    # Sort rows by sku
    rows.sort(key=lambda r: r["sku"])

    return {
        "spg_id": spg.id,
        "spg_code": spg.code,
        "spg_name": spg.name,
        "sections": sections_out,
        "rows": rows,
        "totals": {
            "planned": totals_planned,
            "completed": totals_completed,
            "in_work": totals_in_work,
            "issued": totals_issued,
            "remainders": totals_remainders,
            "spg_available": totals_remainders,
            "negative_total": neg_total,
            "negative_remainder_count": neg_count,
        },
    }
