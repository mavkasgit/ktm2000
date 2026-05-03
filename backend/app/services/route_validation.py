from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import PlanPosition
from app.models.product import Product
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.route_resolution import resolve_route_signature
from app.services.route_matcher import find_route


ROUTE_ERROR_CODES = {
    "route_not_matching_import_signature",
    "route_missing_required_step",
    "route_missing_pack_additional_operation",
    "route_primary_operation_mismatch",
}


async def validate_route_match(db: AsyncSession, position: PlanPosition) -> list[str]:
    if position.product_id is None:
        return []

    # Skip validation when there is no import payload with route information
    if not position.source_payload or position.source_payload.get("output_kind") is None:
        return []

    product = await db.get(Product, position.product_id) if position.product_id else None
    route = await find_route(db, product) if product else None
    if route is None:
        return []

    steps = (
        await db.execute(
            select(RouteStep)
            .where(RouteStep.route_id == route.id)
            .order_by(RouteStep.sequence)
        )
    ).scalars().all()
    if not steps:
        return []

    # Load section kinds
    section_kinds: dict[int, str] = {}
    for step in steps:
        section = await db.get(Section, step.section_id)
        if section:
            section_kinds[step.section_id] = section.kind

    active_signature = [
        _route_step_token(step, section_kinds.get(step.section_id, "production"))
        for step in steps
    ]

    expected = resolve_route_signature(position.source_payload or {})
    expected_signature = [step.step_id for step in expected.steps]

    issues: list[str] = []

    def _find_index(sig: list[str], *needles: str) -> int | None:
        for i, token in enumerate(sig):
            for needle in needles:
                if needle in token:
                    return i
        return None

    # --- Key nodes check ---
    issue_idx = _find_index(active_signature, "ISSUE", "WH")
    anod_idx = _find_index(active_signature, "ANOD")
    final_idx = _find_index(active_signature, "FINAL", "FG_WH")

    expected_issue_idx = _find_index(expected_signature, "ISSUE", "WH")
    expected_anod_idx = _find_index(expected_signature, "ANOD")
    expected_final_idx = _find_index(expected_signature, "FINAL", "FG_WH")

    if expected_issue_idx is not None and issue_idx is None:
        issues.append("route_missing_required_step: missing issue/wh step")
    if expected_anod_idx is not None and anod_idx is None:
        issues.append("route_missing_required_step: missing ANOD step")
    if expected_final_idx is not None and final_idx is None:
        issues.append("route_missing_required_step: missing final/fg_wh step")

    # Order of key nodes
    if issue_idx is not None and anod_idx is not None and final_idx is not None:
        if not (issue_idx < anod_idx < final_idx):
            issues.append("route_not_matching_import_signature: invalid order of key nodes")

    # --- Primary operation check ---
    primary_codes = {"DRILL", "PRESS_WINDOW", "PRESS_COMB"}
    active_primaries = [token for token in active_signature if token in primary_codes]
    expected_primary = expected.primary_operation

    if expected_primary in primary_codes:
        if expected_primary not in active_signature:
            issues.append(
                f"route_primary_operation_mismatch: expected {expected_primary}"
            )
    elif active_primaries:
        issues.append("route_primary_operation_mismatch: unexpected primary operation in route")

    # --- Additional pack operations check ---
    # PACK_* are attributes of PACK step, not independent route steps.
    if expected.additional_pack_operations:
        if "PACK" not in active_signature:
            issues.append("route_missing_required_step: missing PACK step for additional pack operations")
        unsupported = [op for op in expected.additional_pack_operations if op not in {"PACK_GLUE", "PACK_DIFFUSER", "PACK_CUSTOM"}]
        if unsupported:
            issues.append("route_missing_pack_additional_operation: unsupported " + ", ".join(sorted(set(unsupported))))

    # --- Branch check ---
    inter_idx = _find_index(active_signature, "INTER")
    expected_has_wip = (
        _find_index(expected_signature, "WIP_WH") is not None
        or _find_index(expected_signature, "INTER") is not None
    )

    if expected.output_kind == "semi_finished_shipment":
        # After ANOD should go directly to FINAL, no INTER/WIP
        if anod_idx is not None and inter_idx is not None and inter_idx > anod_idx:
            issues.append(
                "route_not_matching_import_signature: expected direct final branch (semi-finished)"
            )
    elif expected.output_kind == "finished_good":
        # Must have INTER after ANOD
        if anod_idx is not None and (inter_idx is None or inter_idx < anod_idx):
            issues.append(
                "route_not_matching_import_signature: expected WIP branch (finished good)"
            )

    return issues


def _route_step_token(step: RouteStep, section_kind: str) -> str:
    op_code = (step.operation_code or "").strip().upper() if step.operation_code else ""
    if op_code:
        if op_code in {"DRILL", "PRESS_WINDOW", "PRESS_COMB", "SHOT", "ANOD", "SAW", "PACK", "PACK_GLUE", "PACK_DIFFUSER"}:
            return op_code
        if op_code == "ISSUE_RAW":
            return "ISSUE"
        if op_code == "MOVE_TO_WIP":
            return "INTER"
        if op_code == "ACCEPT_FINISHED":
            return "FINAL"

    if section_kind == "raw_stock":
        return "ISSUE"
    if section_kind == "wip_stock":
        return "INTER"
    if section_kind == "finished_stock":
        return "FINAL"
    if step.operation_name in ("Дробеструй", "SHOT"):
        return "SHOT"
    if step.operation_name in ("Анодирование", "Анод", "ANOD"):
        return "ANOD"
    if step.operation_name in ("Пила", "SAW"):
        return "SAW"
    if step.operation_name in ("Упаковка", "PACK"):
        return "PACK"
    if step.operation_name in ("Сверло", "DRILL"):
        return "DRILL"
    return step.operation_name.upper()
