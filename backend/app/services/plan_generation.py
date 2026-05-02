from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bom import BOM, BOMLine
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus, ProductionPlan, ProductionPlanStatus
from app.models.release_batch import ReleaseBatch, ReleaseBatchPosition, ReleaseBatchStatus, ReleaseBatchType
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus


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
        route = await _get_active_route(db, position)
        await _validate_active_bom(db, position)
        steps = await _get_route_steps_with_sections(db, route)
        remaining = await _remaining_quantity(db, position)
        if release_quantity <= 0:
            raise ValueError("Release quantity must be > 0")
        if release_quantity > remaining:
            raise ValueError("Release quantity exceeds approved remaining quantity")

        db.add(
            ReleaseBatchPosition(
                release_batch_id=batch.id,
                plan_position_id=position.id,
                release_quantity=release_quantity,
                route_id=route.id,
                route_version=route.version,
                route_snapshot=_route_snapshot(route, steps),
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

        steps = sorted(batch_position.route_snapshot.get("steps", []), key=lambda step: step["sequence"])
        for index, step in enumerate(steps):
            line = SectionPlanLine(
                internal_plan_id=internal_plan.id,
                plan_position_id=position.id,
                section_id=step["section_id"],
                product_id=position.product_id,
                route_id=batch_position.route_id,
                route_step_id=step["route_step_id"],
                sequence=step["sequence"],
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
                    status=WorkTaskStatus.ready if index == 0 else WorkTaskStatus.waiting_previous,
                    due_date=line.due_date,
                )
            )
            tasks_created += 1

        released_total = await _released_quantity(db, position)
        position.status = PlanPositionStatus.released if released_total >= position.quantity else PlanPositionStatus.approved
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
                "route_version": position.route_version,
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


async def _get_active_route(db: AsyncSession, position: PlanPosition) -> ProductionRoute:
    route = await db.scalar(select(ProductionRoute).where(ProductionRoute.product_id == position.product_id, ProductionRoute.is_active.is_(True)))
    if route is None:
        raise ValueError("Active route not found")
    return route


async def _validate_active_bom(db: AsyncSession, position: PlanPosition) -> None:
    bom = await db.scalar(select(BOM).where(BOM.product_id == position.product_id, BOM.is_active.is_(True)))
    if bom is None:
        raise ValueError("Active BOM not found")
    line = await db.scalar(select(BOMLine).where(BOMLine.bom_id == bom.id).limit(1))
    if line is None:
        raise ValueError("Active BOM has no lines")


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


def _route_snapshot(route: ProductionRoute, steps: list[tuple[RouteStep, Section]]) -> dict:
    return {
        "route_id": route.id,
        "route_name": route.name,
        "route_version": route.version,
        "steps": [
            {
                "route_step_id": step.id,
                "sequence": step.sequence,
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "operation_name": step.operation_name,
                "requires_acceptance": step.requires_acceptance,
                "allow_parallel": step.allow_parallel,
                "is_final": step.is_final,
            }
            for step, section in steps
        ],
    }


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
