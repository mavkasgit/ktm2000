from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.techcard import Techcard, TechcardLine
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus, PositionStatusHistory, ProductionPlan, ProductionPlanStatus
from app.models.product import Product
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition, ReleaseBatchStatus, ReleaseBatchType
from app.models.route import ProductionRoute, RouteStep, SectionOperation
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.plan_validation import _find_paired_techcard, _paired_component_skus


async def create_release_batch(
    db: AsyncSession,
    *,
    production_plan_id: int,
    positions: list[dict] | None = None,
    batch_type: ReleaseBatchType = ReleaseBatchType.manual,
    name: str | None = None,
) -> dict:
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise ValueError("Production plan not found")
    if plan.status not in {ProductionPlanStatus.approved, ProductionPlanStatus.partially_released}:
        raise ValueError("Production plan must be approved before release")

    selected_positions = await _select_release_positions(db, production_plan_id, positions)
    if not selected_positions:
        raise ValueError("No approved positions selected")

    batch = ReleaseBatch(
        batch_no=_make_batch_no(),
        production_plan_id=production_plan_id,
        name=name or f"Release {plan.plan_no}",
        batch_type=batch_type,
        horizon_start=plan.period_start,
        horizon_end=plan.period_end,
    )
    db.add(batch)
    await db.flush()

    for position, release_quantity in selected_positions:
        await _validate_active_techcard(db, position)

        # Position must have a persisted route_id (from import)
        if position.route_id is None:
            raise ValueError(f"Position {position.id} has no route assigned - cannot release without route")

        route = await db.get(ProductionRoute, position.route_id)
        if route is None or not route.is_active:
            raise ValueError(f"Route for position {position.id} is not active")

        steps = await _get_route_steps_with_sections(db, route)
        remaining = await _remaining_quantity(db, position)
        if release_quantity <= 0:
            raise ValueError("Release quantity must be > 0")
        if release_quantity > remaining:
            raise ValueError("Release quantity exceeds approved remaining quantity")

        section_ids = {section.id for _step, section in steps}
        operation_names_by_key = {
            (op.section_id, op.operation_code): op.operation_name
            for op in (
                await db.execute(select(SectionOperation).where(SectionOperation.section_id.in_(section_ids)))
            ).scalars().all()
        }

        db.add(
            ReleaseBatchPosition(
                release_batch_id=batch.id,
                plan_position_id=position.id,
                release_quantity=release_quantity,
                route_id=route.id,
                route_snapshot=await _route_snapshot(db, route, steps, position, operation_names_by_key),
            )
        )

    await db.flush()
    return await get_release_batch_summary(db, batch.id)


async def release_batch(db: AsyncSession, release_batch_id: int) -> dict:
    batch = await db.get(ReleaseBatch, release_batch_id)
    if batch is None:
        raise ValueError("Release batch not found")
    if batch.status == ReleaseBatchStatus.cancelled:
        raise ValueError("Cancelled release batch cannot be released")

    existing = await db.scalar(select(InternalPlan).where(InternalPlan.release_batch_id == release_batch_id))
    if existing is not None:
        return await get_release_batch_summary(db, release_batch_id)

    batch_positions = (
        await db.execute(
            select(ReleaseBatchPosition).where(ReleaseBatchPosition.release_batch_id == release_batch_id).order_by(ReleaseBatchPosition.id)
        )
    ).scalars().all()
    if not batch_positions:
        raise ValueError("Release batch has no positions")

    internal_plan = InternalPlan(production_plan_id=batch.production_plan_id, release_batch_id=batch.id)
    db.add(internal_plan)
    await db.flush()

    tasks_created = 0
    for batch_position in batch_positions:
        position = await db.get(PlanPosition, batch_position.plan_position_id)
        if position is None:
            raise ValueError("Plan position not found")
        if position.status not in {PlanPositionStatus.approved, PlanPositionStatus.released}:
            raise ValueError("Only approved positions can be released")
        if position.route_id is None:
            raise ValueError(f"Position #{position.id} has no route assigned")

        # Resolve product_id for paired profile positions
        effective_product_id = position.product_id
        if effective_product_id is None:
            paired_techcard = await _find_paired_techcard(db, _paired_component_skus(position))
            if paired_techcard is None:
                raise ValueError(f"Position #{position.id}: no paired techcard found for product resolution")
            # Get the first component product from the paired techcard
            first_component = await db.scalar(
                select(TechcardLine.component_product_id)
                .where(TechcardLine.techcard_id == paired_techcard.id)
                .limit(1)
            )
            if first_component is None:
                raise ValueError(f"Position #{position.id}: paired techcard has no component products")
            effective_product_id = first_component

        steps = sorted(batch_position.route_snapshot.get("steps", []), key=lambda step: step["sequence"])

        # Group steps by combined_op_group to avoid duplicate SectionPlanLines
        # Steps with same combined_op_group and section_id should be merged into one line
        grouped_steps: list[list[dict]] = []
        current_group: list[dict] = []
        current_cog: str | None = None
        current_section_id: int | None = None

        for step in steps:
            step_cog = step.get("combined_op_group")
            step_section = step["section_id"]

            if step_cog is not None and step_cog == current_cog and step_section == current_section_id:
                # Continue current combined group
                current_group.append(step)
            else:
                # Start new group
                if current_group:
                    grouped_steps.append(current_group)
                current_group = [step]
                current_cog = step_cog
                current_section_id = step_section

        if current_group:
            grouped_steps.append(current_group)

        line_index = 0
        for group in grouped_steps:
            primary_step = group[0]
            line = SectionPlanLine(
                internal_plan_id=internal_plan.id,
                plan_position_id=position.id,
                section_id=primary_step["section_id"],
                product_id=effective_product_id,
                route_id=batch_position.route_id,
                route_step_id=primary_step["route_step_id"],
                sequence=primary_step["sequence"],
                planned_quantity=batch_position.release_quantity,
                due_date=position.due_date,
            )
            db.add(line)
            await db.flush()
            db.add(
                WorkTask(
                    section_plan_line_id=line.id,
                    section_id=line.section_id,
                    product_id=line.product_id,
                    route_step_id=line.route_step_id,
                    planned_quantity=line.planned_quantity,
                    status=WorkTaskStatus.ready if line_index == 0 else WorkTaskStatus.waiting_previous,
                    due_date=line.due_date,
                )
            )
            tasks_created += 1
            line_index += 1

        released_total = await _released_quantity(db, position)
        new_status = PlanPositionStatus.released if released_total >= position.quantity else PlanPositionStatus.approved
        if position.status != new_status and new_status == PlanPositionStatus.released:
            history = PositionStatusHistory(
                plan_position_id=position.id,
                from_status=position.status.value,
                to_status=PlanPositionStatus.released.value,
            )
            db.add(history)
        position.status = new_status
        position.released_at = datetime.now(UTC) if position.status == PlanPositionStatus.released else None

    batch.status = ReleaseBatchStatus.released
    batch.released_at = datetime.now(UTC)
    await _refresh_plan_release_status(db, batch.production_plan_id)
    await db.flush()
    summary = await get_release_batch_summary(db, release_batch_id)
    summary["tasks_created"] = tasks_created
    return summary


async def get_release_batch_summary(db: AsyncSession, release_batch_id: int) -> dict:
    batch = await db.get(ReleaseBatch, release_batch_id)
    if batch is None:
        raise ValueError("Release batch not found")
    positions = (
        await db.execute(
            select(ReleaseBatchPosition).where(ReleaseBatchPosition.release_batch_id == release_batch_id).order_by(ReleaseBatchPosition.id)
        )
    ).scalars().all()
    internal_plan = await db.scalar(select(InternalPlan).where(InternalPlan.release_batch_id == release_batch_id))
    task_count = 0
    if internal_plan is not None:
        task_count = await db.scalar(
            select(func.count(WorkTask.id))
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.internal_plan_id == internal_plan.id)
        )
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "production_plan_id": batch.production_plan_id,
        "status": batch.status.value,
        "internal_plan_id": internal_plan.id if internal_plan else None,
        "positions": [
            {
                "id": position.id,
                "plan_position_id": position.plan_position_id,
                "release_quantity": str(position.release_quantity),
                "route_id": position.route_id,
                "route_snapshot": position.route_snapshot,
            }
            for position in positions
        ],
        "task_count": task_count or 0,
    }


async def _select_release_positions(
    db: AsyncSession, production_plan_id: int, requested: list[dict] | None
) -> list[tuple[PlanPosition, Decimal]]:
    if requested:
        result: list[tuple[PlanPosition, Decimal]] = []
        for item in requested:
            position = await db.get(PlanPosition, item["plan_position_id"])
            if position is None or position.production_plan_id != production_plan_id:
                raise ValueError("Selected plan position not found")
            if position.status != PlanPositionStatus.approved:
                raise ValueError("Selected plan position must be approved")
            quantity = Decimal(str(item.get("release_quantity") or position.quantity))
            result.append((position, quantity))
        return result

    positions = (
        await db.execute(
            select(PlanPosition).where(
                PlanPosition.production_plan_id == production_plan_id,
                PlanPosition.status == PlanPositionStatus.approved,
            )
        )
    ).scalars().all()
    return [(position, position.quantity) for position in positions]


async def _validate_active_techcard(db: AsyncSession, position: PlanPosition) -> None:
    techcard = await db.scalar(select(Techcard).where(Techcard.product_id == position.product_id, Techcard.is_active.is_(True)))
    if techcard is None:
        raise ValueError("Активная техкарта не найдена")
    line = await db.scalar(select(TechcardLine).where(TechcardLine.techcard_id == techcard.id).limit(1))
    if line is None:
        raise ValueError("Активная техкарта не содержит строк")


async def _get_route_steps_with_sections(db: AsyncSession, route: ProductionRoute) -> list[tuple[RouteStep, Section]]:
    steps = (
        await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))
    ).scalars().all()
    if not steps:
        raise ValueError("Route has no steps")
    result = []
    previous = 0
    for step in steps:
        if step.sequence <= previous:
            raise ValueError("Route sequence is invalid")
        previous = step.sequence
        section = await db.get(Section, step.section_id)
        if section is None or not section.is_active:
            raise ValueError("Route contains inactive section")
        result.append((step, section))
    return result


def _dynamic_route_snapshot(
    profile: RouteRuleProfile,
    steps: list[dict],
    position: PlanPosition | None = None,
    operation_names_by_key: dict[tuple[int, str], str] | None = None,
) -> dict:
    """Создать route_snapshot для динамического маршрута.

    steps — список dict из build_route_steps_for_release
    """
    op_names = operation_names_by_key or {}
    return {
        "route_id": None,  # Dynamic route
        "route_name": f"Dynamic: {profile.name}",
        "profile_id": profile.id,
        "profile_code": profile.code,
        "steps": [
            {
                "route_step_id": None,  # No static RouteStep
                "sequence": step["sequence"],
                "section_id": step["section_id"],
                "section_code": step["section_code"],
                "section_name": step["section_name"],
                "section_kind": step["section_kind"],
                "group_code": step.get("group_code"),
                "group_name": step.get("group_name"),
                "operation_code": step["operation_code"],
                "operation_name": op_names.get(
                    (step["section_id"], step["operation_code"]),
                    step["operation_name"],
                ) if step["operation_code"] else step["operation_name"],
                "requires_acceptance": True,
                "allow_parallel": False,
                "is_final": step.get("is_final", False),
                "combined_op_group": step.get("combined_op_group"),
            }
            for step in steps
        ],
    }


async def _route_snapshot(
    db: AsyncSession,
    route: ProductionRoute,
    steps: list[tuple[RouteStep, Section]],
    position: PlanPosition | None = None,
    operation_names_by_key: dict[tuple[int, str], str] | None = None,
) -> dict:
    op_names = operation_names_by_key or {}
    snapshot_steps = []
    for step, section in steps:
        operation_code = step.operation_code
        snapshot_steps.append({
            "route_step_id": step.id,
            "sequence": step.sequence,
            "section_id": section.id,
            "section_code": section.code,
            "section_name": section.name,
            "section_kind": section.kind,
            "operation_code": operation_code,
            "operation_name": await _resolve_route_step_operation_name(db, step, section, position, op_names),
            "requires_acceptance": step.requires_acceptance,
            "allow_parallel": step.allow_parallel,
            "is_final": step.is_final,
            "combined_op_group": step.combined_op_group,
        })
    return {
        "route_id": route.id,
        "route_name": route.name,
        "steps": snapshot_steps,
    }


async def _resolve_route_step_operation_name(
    db: AsyncSession,
    step: RouteStep,
    section: Section,
    position: PlanPosition | None,
    operation_names_by_key: dict[tuple[int, str], str],
) -> str:
    """Return display operation name for a route step."""
    if step.operation_code is not None:
        return operation_names_by_key.get((section.id, step.operation_code), step.operation_name)
    return step.operation_name


async def _remaining_quantity(db: AsyncSession, position: PlanPosition) -> Decimal:
    return position.quantity - await _released_quantity(db, position)


async def _released_quantity(db: AsyncSession, position: PlanPosition) -> Decimal:
    value = await db.scalar(
        select(func.coalesce(func.sum(ReleaseBatchPosition.release_quantity), 0))
        .join(ReleaseBatch, ReleaseBatch.id == ReleaseBatchPosition.release_batch_id)
        .where(
            ReleaseBatchPosition.plan_position_id == position.id,
            ReleaseBatch.status != ReleaseBatchStatus.cancelled,
        )
    )
    return Decimal(str(value or 0))


async def _refresh_plan_release_status(db: AsyncSession, production_plan_id: int) -> None:
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        return
    positions = (
        await db.execute(select(PlanPosition).where(PlanPosition.production_plan_id == production_plan_id))
    ).scalars().all()
    if positions and all(position.status == PlanPositionStatus.released for position in positions):
        plan.status = ProductionPlanStatus.released
    elif any(position.status == PlanPositionStatus.released for position in positions):
        plan.status = ProductionPlanStatus.partially_released


def _make_batch_no() -> str:
    return f"RB-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
