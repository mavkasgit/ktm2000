"""Helpers for keeping ``RouteStep`` (legacy) and ``RouteStage`` (new) in sync.

During the transition period every code path that creates a
``RouteStep`` must also create the corresponding ``RouteStage`` and
``RouteOperation`` rows, so that plan generation, shopfloor display,
and the new module all see the same data.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteOperation, RouteStage, RouteStep


def _merge_combined_group(steps: list[RouteStep]) -> list[list[RouteStep]]:
    """Group legacy ``RouteStep`` rows that share a combined group + section.

    Mirrors the legacy plan-generation grouping: same ``combined_op_group``
    on the same ``section_id`` → one stage.
    """
    groups: list[list[RouteStep]] = []
    current: list[RouteStep] = []
    current_cog: str | None = None
    current_section_id: int | None = None

    for step in sorted(steps, key=lambda s: s.sequence):
        step_cog = step.combined_op_group
        same_group = (
            step_cog is not None
            and step_cog == current_cog
            and step.section_id == current_section_id
        )
        if same_group:
            current.append(step)
        else:
            if current:
                groups.append(current)
            current = [step]
            current_cog = step_cog
            current_section_id = step.section_id
    if current:
        groups.append(current)
    return groups


async def sync_stages_for_steps(
    db: AsyncSession, route_id: int, steps: Iterable[RouteStep]
) -> list[RouteStage]:
    """Create/refresh ``RouteStage`` + ``RouteOperation`` rows for a route.

    Call this after creating a batch of ``RouteStep`` rows.  The
    returned list is the ordered list of stages (one per group) for
    plan generation / display.
    """
    step_list = sorted(list(steps), key=lambda s: s.sequence)
    if not step_list:
        return []

    existing_stages = (
        await db.execute(
            __import__("sqlalchemy").select(RouteStage).where(
                RouteStage.route_id == route_id
            )
        )
    ).scalars().all()
    for st in existing_stages:
        await db.delete(st)
    await db.flush()

    groups = _merge_combined_group(step_list)
    new_stages: list[RouteStage] = []
    for group in groups:
        primary = group[0]
        stage = RouteStage(
            route_id=primary.route_id,
            sequence=primary.sequence,
            section_id=primary.section_id,
            is_significant=primary.is_significant,
            norm_time_minutes=primary.norm_time_minutes,
            requires_acceptance=primary.requires_acceptance,
            allow_parallel=primary.allow_parallel,
            is_final=any(s.is_final for s in group),
            sort_order=primary.sequence,
            route_step_id=primary.id,
        )
        db.add(stage)
        await db.flush()
        for idx, step in enumerate(group, start=1):
            db.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=idx,
                    operation_code=step.operation_code,
                    operation_name=step.operation_name,
                )
            )
        new_stages.append(stage)
    await db.flush()
    return new_stages


async def sync_stage_for_step(db: AsyncSession, step: RouteStep) -> RouteStage:
    """Sync a single ``RouteStep`` into its own ``RouteStage``."""
    stages = await sync_stages_for_steps(db, step.route_id, [step])
    return stages[0] if stages else None  # type: ignore[return-value]
