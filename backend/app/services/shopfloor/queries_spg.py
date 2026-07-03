from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import RouteStage
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction


async def get_spg_snapshot(
    db: AsyncSession,
    *,
    spg_id: int,
) -> dict:
    """Return aggregated snapshot for a Storage Production Group.

    For every product that has work_tasks in any of the SPG's sections:
      - per-section quantities (planned, completed, issued, available)
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
    task_info_rows = (
        select(
            WorkTask.id,
            WorkTask.product_id,
            WorkTask.section_id,
            WorkTask.planned_quantity,
            WorkTask.section_plan_line_id,
            SectionPlanLine.sequence,
        )
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .join(PlanPosition, SectionPlanLine.plan_position_id == PlanPosition.id)
        .where(
            WorkTask.section_id.in_(section_ids),
            PlanPosition.deleted_at.is_(None),
            PlanPosition.status != PlanPositionStatus.cancelled,
            SectionPlanLine.plan_position_id.notin_(completed_positions_subq),
        )
    )
    task_info = (await db.execute(task_info_rows)).all()
    if not task_info:
        task_rows = []
    else:
        matching_task_ids = [r.id for r in task_info]
        from app.stock.services import StockProjectionManager
        pm = StockProjectionManager()
        tasks_cache = await pm.get_tasks_cache_bulk(db, matching_task_ids)

        # Aggregate per (product_id, section_id) in Python
        from collections import defaultdict
        agg: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: {
            "planned": Decimal("0"), "completed": Decimal("0"), "issued": Decimal("0"),
            "transferred": Decimal("0"), "received": Decimal("0"), "available": Decimal("0"),
        })
        for tid, pid, sid, planned_qty, spl_id, seq in task_info:
            key = (pid, sid)
            cache = tasks_cache.get(tid, {})
            agg[key]["planned"] += planned_qty
            agg[key]["completed"] += cache.get("completed_quantity", Decimal("0"))
            agg[key]["issued"] += cache.get("issued_quantity", Decimal("0"))
            agg[key]["transferred"] += cache.get("transferred_quantity", Decimal("0"))
            agg[key]["received"] += cache.get("received_quantity", Decimal("0"))
            agg[key]["available"] += cache.get("available_quantity", Decimal("0"))

        # Format as row tuples (matching original structure)
        task_rows = [
            type("Row", (), {
                "product_id": pid, "section_id": sid,
                "planned": vals["planned"], "completed": vals["completed"],
                "available": vals["available"], "issued": vals["issued"],
                "transferred": vals["transferred"], "received": vals["received"],
            })
            for (pid, sid), vals in agg.items()
        ]

    # Aggregate StockBalance per product_id for this SPG's sections
    rem_agg_q = (
        select(
            StockBalance.product_id,
            func.sum(StockBalance.quantity).label("remainder_total"),
        )
        .where(
            StockBalance.location_id.in_(section_ids),
            StockBalance.quantity > 0,
            StockBalance.quality_state == QualityState.GOOD,
        )
        .group_by(StockBalance.product_id)
    )
    rem_rows = (await db.execute(rem_agg_q)).all()

    neg_total = 0.0
    neg_count = 0
    neg_count_per_product: dict[int, int] = {}

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
    totals_remainders = 0.0
    totals_issued = 0.0

    for pid in sorted(product_ids):
        product = product_map.get(pid)
        if product is None:
            continue

        per_section: dict[str, dict] = {}
        planned_total = 0.0
        completed_total = 0.0
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
                issued_total += t["issued"]

                # Current section = where most material is (issued + available)
                location_val = t["issued"] + t["available"]
                if location_val > max_location_value:
                    max_location_value = location_val
                    current_section_code = scode
            elif rem != 0:
                per_section[scode] = {
                    "planned": 0, "completed": 0, "available": 0,
                    "issued": 0, "transferred": 0, "received": 0, "remainder": rem,
                }

        completion_pct = round(completed_total / planned_total * 100, 1) if planned_total > 0 else 0.0

        rows.append({
            "product_id": pid,
            "sku": product.sku,
            "product_name": product.name,
            "planned_total": planned_total,
            "completed_total": completed_total,
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
            "issued": totals_issued,
            "remainders": totals_remainders,
            "spg_available": totals_remainders,
            "negative_total": neg_total,
            "negative_remainder_count": neg_count,
        },
    }
