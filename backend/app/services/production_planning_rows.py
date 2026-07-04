from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus, PositionStatusHistory
from app.models.audit_log import AuditLog, AuditEntityType
from app.models.route import RouteStage, SectionOperation
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import Reason, StockTransaction
from app.services.route_matcher import ResolvedRouteInfo, resolve_position_route, make_position_route_cache_key

MANUAL_ROUTE_PASS_PREFIX = "manual_route_pass:"


async def _get_stage_with_operations(db: AsyncSession, stage_id: int) -> RouteStage | None:
    return (
        await db.execute(
            select(RouteStage)
            .options(selectinload(RouteStage.operations))
            .where(RouteStage.id == stage_id)
        )
    ).scalar_one_or_none()


def _resolve_stage_operation_code(stage: RouteStage) -> str | None:
    return stage.operations[0].operation_code if stage.operations else None


def _resolve_stage_operation_name(stage: RouteStage, operation_names_by_key: dict[tuple[int, str], str]) -> str:
    op_names = []
    for op in stage.operations:
        name = operation_names_by_key.get((stage.section_id, op.operation_code), op.operation_name) if op.operation_code else op.operation_name
        op_names.append(name)
    return " / ".join(op_names) if op_names else ""


def _to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _clamp_percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    value = (numerator / denominator) * 100.0
    return round(max(0.0, min(100.0, value)), 1)


def _summarize_task_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_started"
    status_set = set(statuses)
    if status_set == {"completed"}:
        return "completed"
    if "in_progress" in status_set:
        return "in_progress"
    if "ready" in status_set:
        return "ready"
    if "waiting_previous" in status_set:
        return "waiting_previous"
    if status_set == {"cancelled"}:
        return "cancelled"
    return statuses[0]


def _resolved_route_error(route_info: ResolvedRouteInfo) -> str | None:
    if route_info.error:
        return route_info.error
    if route_info.route_id is None:
        return "route_not_found"
    return None


def _event_at_iso(*, performed_at, accounted_at, created_at) -> str | None:
    event_at = performed_at or accounted_at or created_at
    return event_at.isoformat() if event_at else None


def _is_manual_route_pass(value: str | None) -> bool:
    return bool(value and value.startswith(MANUAL_ROUTE_PASS_PREFIX))


async def _resolve_effective_product_id(
    db: AsyncSession, position: PlanPosition
) -> int | None:
    """Резолвит effective_product_id для позиции плана.

    Возвращает position.product_id, если он задан. Иначе пытается найти
    парный техкарту и взять первый компонент из неё (как в release_batch).
    Возвращает None, если продукт не резолвится.
    """
    if position.product_id is not None:
        return position.product_id
    try:
        from app.services.plan_generation import _find_paired_techcard, _paired_component_skus
    except ImportError:
        return None
    paired_techcard = await _find_paired_techcard(db, _paired_component_skus(position))
    if paired_techcard is None:
        return None
    from app.models.techcard import TechcardLine
    first_component = await db.scalar(
        select(TechcardLine.component_product_id)
        .where(TechcardLine.techcard_id == paired_techcard.id)
        .limit(1)
    )
    return first_component


async def list_production_planning_rows(db: AsyncSession) -> list[dict]:
    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.status.in_([PlanPositionStatus.approved, PlanPositionStatus.released, PlanPositionStatus.cancelled]))
            .where(PlanPosition.deleted_at.is_(None))
            .order_by(PlanPosition.production_plan_id.desc(), PlanPosition.source_row_number, PlanPosition.id)
        )
    ).scalars().all()
    if not positions:
        return []

    position_ids = [pos.id for pos in positions]
    has_tasks_rows = (
        await db.execute(
            select(SectionPlanLine.plan_position_id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    has_tasks_set = {row[0] for row in has_tasks_rows}

    # Count total and completed tasks per position to detect fully completed positions
    task_counts = (
        await db.execute(
            select(
                SectionPlanLine.plan_position_id,
                func.count(WorkTask.id).label("total_tasks"),
                func.sum(
                    case((WorkTask.status == WorkTaskStatus.completed, 1), else_=0)
                ).label("completed_tasks"),
            )
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    completed_set = {
        row.plan_position_id
        for row in task_counts
        if row.total_tasks > 0 and row.completed_tasks == row.total_tasks
    }

    # Also treat position as completed when the final route stage task is completed.
    final_step_completed_rows = (
        await db.execute(
            select(SectionPlanLine.plan_position_id)
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
            .where(
                SectionPlanLine.plan_position_id.in_(position_ids),
                WorkTask.status == WorkTaskStatus.completed,
                RouteStage.is_final.is_(True),
            )
            .group_by(SectionPlanLine.plan_position_id)
        )
    ).all()
    final_step_completed_set = {row[0] for row in final_step_completed_rows}
    completed_set |= final_step_completed_set

    # Fetch current stage info: first in_progress or ready task per position
    current_stage_rows = (
        await db.execute(
            select(
                SectionPlanLine.plan_position_id,
                RouteStage.section_id,
                RouteStage.sequence,
                Section.code.label("section_code"),
                Section.name.label("section_name"),
                WorkTask.status.label("task_status"),
                RouteStage.id.label("stage_id"),
            )
            .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
            .join(Section, Section.id == RouteStage.section_id)
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id.in_(position_ids))
            .where(WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.ready]))
            .order_by(
                SectionPlanLine.plan_position_id,
                WorkTask.status.desc(),  # in_progress before ready
                RouteStage.sequence,
            )
        )
    ).all()

    # Fallback: get first task stage for positions without in_progress/ready
    positions_without_active = [pid for pid in position_ids if pid not in {r.plan_position_id for r in current_stage_rows}]
    fallback_rows = []
    if positions_without_active:
        fallback_rows = (
            await db.execute(
                select(
                    SectionPlanLine.plan_position_id,
                    RouteStage.section_id,
                    RouteStage.sequence,
                    Section.code.label("section_code"),
                    Section.name.label("section_name"),
                    WorkTask.status.label("task_status"),
                    RouteStage.id.label("stage_id"),
                )
                .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
                .join(Section, Section.id == RouteStage.section_id)
                .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                .where(SectionPlanLine.plan_position_id.in_(positions_without_active))
                .order_by(
                    SectionPlanLine.plan_position_id,
                    RouteStage.sequence,
                )
            )
        ).all()

    # Load operation names by section/code to resolve operation names
    all_section_ids = {r.section_id for r in current_stage_rows} | {r.section_id for r in fallback_rows}
    operation_names_by_key = {}
    if all_section_ids:
        operation_names_by_key = {
            (op.section_id, op.operation_code): op.operation_name
            for op in (
                await db.execute(
                    select(SectionOperation).where(SectionOperation.section_id.in_(all_section_ids))
                )
            ).scalars().all()
        }

    # Загружаем все необходимые RouteStage с их operations одним запросом
    stage_ids = {r.stage_id for r in current_stage_rows}
    if fallback_rows:
        stage_ids |= {r.stage_id for r in fallback_rows}
    
    stages_by_id = {}
    if stage_ids:
        stages_list = (
            await db.execute(
                select(RouteStage)
                .options(selectinload(RouteStage.operations))
                .where(RouteStage.id.in_(stage_ids))
            )
        ).scalars().all()
        stages_by_id = {stage.id: stage for stage in stages_list}

    current_stage_by_position: dict[int, dict] = {}
    
    def process_row(row):
        stage = stages_by_id.get(row.stage_id)
        op_name = _resolve_stage_operation_name(stage, operation_names_by_key) if stage else ""
        op_code = _resolve_stage_operation_code(stage) if stage else None
        return {
            "current_stage_section_id": row.section_id,
            "current_stage_sequence": row.sequence,
            "current_stage_operation_name": op_name,
            "current_stage_operation_code": op_code,
            "current_stage_section_code": row.section_code,
            "current_stage_section_name": row.section_name,
            "current_stage_task_status": row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status),
        }

    for row in current_stage_rows:
        if row.plan_position_id not in current_stage_by_position:
            current_stage_by_position[row.plan_position_id] = process_row(row)

    fallback_rows_by_position: dict[int, list] = {}
    for row in fallback_rows:
        fallback_rows_by_position.setdefault(row.plan_position_id, []).append(row)

    for position_id, rows in fallback_rows_by_position.items():
        if position_id in current_stage_by_position:
            continue
        chosen_row = None
        for row in rows:
            status_value = row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status)
            if status_value not in {"completed", "cancelled"}:
                chosen_row = row
                break
        if chosen_row is None and rows:
            chosen_row = rows[-1]
        if chosen_row is not None:
            current_stage_by_position[position_id] = process_row(chosen_row)


    route_cache: dict[tuple, ResolvedRouteInfo] = {}
    route_steps_cache: dict[int, list[dict]] = {}
    route_remainder_steps_cache: dict[int, list[dict]] = {}

    # Сначала резолвим effective_product_id для каждой позиции и считаем
    # доступные остатки — одним батчем, без N+1.
    position_remainder_steps: dict[int, list[dict]] = {}
    position_effective_product_id: dict[int, int | None] = {}
    for pos in positions:
        position_effective_product_id[pos.id] = await _resolve_effective_product_id(db, pos)

    # Вычислить route_remainder_steps для каждого уникального route_id.
    for pos in positions:
        cache_key = make_position_route_cache_key(pos)
        if cache_key in route_cache:
            route_info = route_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, pos)
            route_cache[cache_key] = route_info

            # Cache route stages for this route
            if route_info.route_id is not None and route_info.route_id not in route_steps_cache:
                stages = (
                    await db.execute(
                        select(RouteStage, Section)
                        .options(selectinload(RouteStage.operations))
                        .join(Section, RouteStage.section_id == Section.id)
                        .where(RouteStage.route_id == route_info.route_id)
                        .where(Section.is_active == True)
                        .order_by(RouteStage.sequence)
                    )
                ).all()
                route_steps_cache[route_info.route_id] = [
                    {
                        "section_id": section.id,
                        "section_icon": section.icon,
                        "section_icon_color": section.icon_color,
                        "sequence": stage.sequence,
                    }
                    for stage, section in stages
                ]
                route_remainder_steps_cache[route_info.route_id] = [
                    {
                        "sequence": stage.sequence,
                        "section_id": section.id,
                        "operation_codes": {op.operation_code for op in (stage.operations or [])},
                    }
                    for stage, section in stages
                ]

    # Считаем доступные остатки по позициям.
    for pos in positions:
        route_info = route_cache[make_position_route_cache_key(pos)]
        remainder_steps = (
            route_remainder_steps_cache.get(route_info.route_id)
            if route_info.route_id is not None
            else None
        )
        if remainder_steps:
            from app.services.position_remainders import compute_available_remainder_quantity
            available = await compute_available_remainder_quantity(
                db,
                effective_product_id=position_effective_product_id.get(pos.id),
                route_steps=remainder_steps,
                position_id=pos.id,
            )
        else:
            available = 0.0
        position_remainder_steps[pos.id] = available

    result: list[dict] = []
    for pos in positions:
        route_info = route_cache[make_position_route_cache_key(pos)]

        has_tasks = pos.id in has_tasks_set
        is_completed = pos.id in completed_set
        raw_stage_info = current_stage_by_position.get(pos.id, {})

        route_steps = route_steps_cache.get(route_info.route_id) if route_info.route_id is not None else None
        result.append(
            {
                "plan_position_id": pos.id,
                "production_plan_id": pos.production_plan_id,
                "source_row_number": pos.source_row_number,
                "source_sku": pos.source_sku,
                "source_name": pos.source_name,
                "quantity": _to_float(pos.quantity),
                "position_status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
                "validation_status": pos.validation_status.value
                if hasattr(pos.validation_status, "value")
                else str(pos.validation_status),
                "route_id": route_info.route_id,
                "route_name": route_info.route_name,
                "route_source": route_info.source,
                "route_origin": route_info.route_origin,
                "route_match_quality": route_info.route_match_quality,
                "route_match_reason": route_info.route_match_reason,
                "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                "route_manual_confirmed_at": (
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                "route_error": _resolved_route_error(route_info),
                "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
                "has_tasks": has_tasks,
                "is_completed": is_completed,
                "current_stage_section_id": raw_stage_info.get("current_stage_section_id"),
                "current_stage_sequence": raw_stage_info.get("current_stage_sequence"),
                "current_stage_operation": raw_stage_info.get("current_stage_operation_name"),
                "current_stage_section_code": raw_stage_info.get("current_stage_section_code"),
                "current_stage_section_name": raw_stage_info.get("current_stage_section_name"),
                "current_stage_task_status": raw_stage_info.get("current_stage_task_status"),
                "route_steps": route_steps,
                "available_remainder_quantity": round(position_remainder_steps.get(pos.id, 0.0), 3),
            }
        )

    return result


async def _load_position_status_history(db: AsyncSession, position_id: int) -> list[dict]:
    """История смен статуса позиции: legacy-таблица + аудит-логи с changes.status."""
    entries: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    legacy_rows = (
        await db.execute(
            select(PositionStatusHistory)
            .where(PositionStatusHistory.plan_position_id == position_id)
            .order_by(PositionStatusHistory.changed_at.asc())
        )
    ).scalars().all()

    for row in legacy_rows:
        changed_at = row.changed_at.isoformat() if row.changed_at else ""
        key = (row.from_status, row.to_status, changed_at)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "id": row.id,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "changed_by": row.changed_by,
                "changed_at": changed_at,
                "reason": row.reason,
            }
        )

    audit_logs = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
            )
            .order_by(AuditLog.created_at.asc())
        )
    ).scalars().all()

    for log in audit_logs:
        changes = log.changes or {}
        before = changes.get("before") or {}
        after = changes.get("after") or {}
        from_status = before.get("status")
        to_status = after.get("status")
        if not from_status or not to_status:
            continue
        changed_at = log.created_at.isoformat() if log.created_at else ""
        key = (str(from_status), str(to_status), changed_at)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "id": log.id,
                "from_status": str(from_status),
                "to_status": str(to_status),
                "changed_by": log.user_id,
                "changed_at": changed_at,
                "reason": log.comment or log.message,
            }
        )

    entries.sort(key=lambda item: item.get("changed_at") or "")
    return entries


async def get_production_planning_row_detail(db: AsyncSession, position_id: int) -> dict | None:
    pos = await db.get(PlanPosition, position_id)
    if pos is None or pos.deleted_at is not None:
        return None

    route_info = await resolve_position_route(db, pos)

    has_tasks = bool(
        await db.scalar(select(func.count(SectionPlanLine.id)).where(SectionPlanLine.plan_position_id == pos.id))
    )

    steps_data: list[dict] = []
    route_snapshot: dict | None = None

    if route_info.route_id is not None:
        stages = (
            await db.execute(
                select(RouteStage, Section)
                .options(selectinload(RouteStage.operations))
                .join(Section, RouteStage.section_id == Section.id)
                .where(RouteStage.route_id == route_info.route_id)
                .order_by(RouteStage.sequence)
            )
        ).all()
        section_ids = {section.id for _stage, section in stages}
        section_name_by_id = {section.id: section.name for _stage, section in stages}
        operation_names_by_key = {
            (operation.section_id, operation.operation_code): operation.operation_name
            for operation in (
                await db.execute(
                    select(SectionOperation).where(SectionOperation.section_id.in_(section_ids))
                )
            ).scalars().all()
        }

        planned_by_stage = {
            row.route_stage_id: _to_float(row.planned_quantity)
            for row in (
                await db.execute(
                    select(
                        SectionPlanLine.route_stage_id.label("route_stage_id"),
                        func.coalesce(func.sum(SectionPlanLine.planned_quantity), 0).label("planned_quantity"),
                    )
                    .where(SectionPlanLine.plan_position_id == pos.id)
                    .group_by(SectionPlanLine.route_stage_id)
                )
            ).all()
        }

        # Этап 4: cached_* колонки удалены, агрегация из StockTransaction
        from app.stock.models import StockTransaction, Reason
        from sqlalchemy import case

        # Get all task_ids for this position
        task_in_pos = (await db.execute(
            select(WorkTask.id, WorkTask.section_plan_line_id, WorkTask.status)
            .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
            .where(SectionPlanLine.plan_position_id == pos.id)
        )).all()

        # Map task_id -> route_stage_id via SectionPlanLine
        spl_ids = [r.section_plan_line_id for r in task_in_pos]
        spl_rows = (await db.execute(
            select(SectionPlanLine.id, SectionPlanLine.route_stage_id)
            .where(SectionPlanLine.id.in_(spl_ids))
        )).all()
        spl_to_stage = {r.id: r.route_stage_id for r in spl_rows}

        # StockTransaction sums GROUP BY task_id, reason
        tx_rows = (await db.execute(
            select(
                StockTransaction.task_id,
                StockTransaction.reason,
                func.sum(StockTransaction.quantity).label("qty"),
            )
            .where(StockTransaction.task_id.in_([r.id for r in task_in_pos]))
            .group_by(StockTransaction.task_id, StockTransaction.reason)
        )).all()

        # Net for transfer_send/receive with compensations
        net_rows = (await db.execute(
            select(
                StockTransaction.task_id,
                StockTransaction.reason,
                func.sum(
                    case(
                        (StockTransaction.compensates_tx_id.is_(None), StockTransaction.quantity),
                        else_=-StockTransaction.quantity,
                    )
                ).label("net"),
            )
            .where(
                StockTransaction.task_id.in_([r.id for r in task_in_pos]),
                StockTransaction.reason.in_([Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]),
            )
            .group_by(StockTransaction.task_id, StockTransaction.reason)
        )).all()

        tx_sums: dict[int, dict[str, Decimal]] = {}
        for tid, reason_val, qty in tx_rows:
            tx_sums.setdefault(tid, {})[reason_val] = qty or Decimal("0")

        net_sums: dict[int, dict[str, Decimal]] = {}
        for tid, reason_val, nq in net_rows:
            net_sums.setdefault(tid, {})[reason_val] = nq or Decimal("0")

        task_aggregates_by_stage: dict[int, dict[str, float]] = {}
        task_statuses_by_stage: dict[int, list[str]] = {}
        for t in task_in_pos:
            stage_id = spl_to_stage.get(t.section_plan_line_id)
            if stage_id is None:
                continue
            sums = tx_sums.get(t.id, {})
            nets = net_sums.get(t.id, {})
            completed = float(sums.get(Reason.COMPLETE.value, Decimal("0")))
            transferred = float(nets.get(Reason.TRANSFER_SEND.value, Decimal("0")))
            rejected = float(sums.get(Reason.SCRAP.value, Decimal("0")))
            stage_totals = task_aggregates_by_stage.setdefault(
                stage_id,
                {"completed_quantity": 0.0, "transferred_quantity": 0.0, "rejected_quantity": 0.0},
            )
            stage_totals["completed_quantity"] += completed
            stage_totals["transferred_quantity"] += transferred
            stage_totals["rejected_quantity"] += rejected
            task_statuses_by_stage.setdefault(stage_id, []).append(
                t.status.value if hasattr(t.status, "value") else str(t.status)
            )

        flow_by_stage: dict[int, dict] = {}
        task_ids_in_pos = [t.id for t in task_in_pos]
        task_id_to_spl = {t.id: t.section_plan_line_id for t in task_in_pos}
        tx_rows = (
            await db.execute(
                select(
                    StockTransaction,
                )
                .where(StockTransaction.task_id.in_(task_ids_in_pos))
                .order_by(StockTransaction.created_at, StockTransaction.id)
            )
        ).scalars().all()

        for tx in tx_rows:
            # Get stage_id from the task's section_plan_line_id
            spl_id = task_id_to_spl.get(tx.task_id)
            if spl_id is None:
                continue
            stage_id = spl_to_stage.get(spl_id)
            if stage_id is None:
                continue

            reason_val = tx.reason.value if hasattr(tx.reason, "value") else str(tx.reason)
            quantity = _to_float(tx.quantity)
            event_sort_dt = tx.created_at
            event_at_iso = tx.created_at.isoformat() if tx.created_at else None

            entry = flow_by_stage.setdefault(
                stage_id,
                {
                    "issued_qty": 0.0,
                    "issued_last_at": None,
                    "issued_last_dt": None,
                    "accounted_good_qty": 0.0,
                    "accounted_reject_qty": 0.0,
                    "accounted_total_qty": 0.0,
                    "accounted_last_at": None,
                    "accounted_last_dt": None,
                    "sent_qty": 0.0,
                    "sent_last_at": None,
                    "sent_last_dt": None,
                    "accepted_by_next_qty": 0.0,
                    "accepted_by_next_last_at": None,
                    "accepted_by_next_last_dt": None,
                    "flow_events": [],
                },
            )

            if reason_val == Reason.TRANSFER_RECEIVE.value:
                entry["issued_qty"] += quantity
                if entry["issued_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["issued_last_dt"]):
                    entry["issued_last_dt"] = event_sort_dt
                    entry["issued_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "receive",
                        "label": "Принято (выдано в работу)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": tx.task_id,
                        "transfer_id": tx.transfer_id,
                        "manual_route_pass": False,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": tx.id,
                    }
                )
            elif reason_val == Reason.COMPLETE.value:
                entry["accounted_good_qty"] += quantity
                entry["accounted_total_qty"] += quantity
                if entry["accounted_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["accounted_last_dt"]):
                    entry["accounted_last_dt"] = event_sort_dt
                    entry["accounted_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "account",
                        "label": "Учтено (годное)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": tx.task_id,
                        "transfer_id": tx.transfer_id,
                        "manual_route_pass": False,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": tx.id,
                    }
                )
            elif reason_val == Reason.SCRAP.value:
                entry["accounted_reject_qty"] += quantity
                entry["accounted_total_qty"] += quantity
                if entry["accounted_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["accounted_last_dt"]):
                    entry["accounted_last_dt"] = event_sort_dt
                    entry["accounted_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "account",
                        "label": "Учтено (брак)",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": tx.task_id,
                        "transfer_id": tx.transfer_id,
                        "manual_route_pass": False,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": tx.id,
                    }
                )
            elif reason_val == Reason.TRANSFER_SEND.value:
                entry["sent_qty"] += quantity
                if entry["sent_last_dt"] is None or (event_sort_dt and event_sort_dt >= entry["sent_last_dt"]):
                    entry["sent_last_dt"] = event_sort_dt
                    entry["sent_last_at"] = event_at_iso
                entry["flow_events"].append(
                    {
                        "step": "transfer",
                        "label": "Передача на след. этап",
                        "quantity": round(quantity, 3),
                        "event_at": event_at_iso,
                        "task_id": tx.task_id,
                        "transfer_id": tx.transfer_id,
                        "from_section_name": section_name_by_id.get(tx.from_location_id),
                        "to_section_name": section_name_by_id.get(tx.to_location_id),
                        "manual_route_pass": False,
                        "_sort_dt": event_sort_dt,
                        "_sort_id": tx.id,
                    }
                )

        transfer_accept_rows = (
            await db.execute(
                select(
                    SectionPlanLine.route_stage_id.label("route_stage_id"),
                    Transfer.id.label("transfer_id"),
                    Transfer.from_task_id.label("from_task_id"),
                    Transfer.from_section_id.label("from_section_id"),
                    Transfer.to_section_id.label("to_section_id"),
                    Transfer.accepted_quantity.label("accepted_quantity"),
                    Transfer.idempotency_key.label("idempotency_key"),
                    Transfer.accepted_at.label("accepted_at"),
                    Transfer.created_at.label("created_at"),
                )
                .join(WorkTask, WorkTask.id == Transfer.from_task_id)
                .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .order_by(Transfer.created_at, Transfer.id)
            )
        ).all()

        for row in transfer_accept_rows:
            stage_id = row.route_stage_id
            accepted_qty = _to_float(row.accepted_quantity)
            if accepted_qty <= 0:
                continue
            is_manual_route_pass = _is_manual_route_pass(row.idempotency_key)
            event_at = row.accepted_at or row.created_at
            event_at_iso = event_at.isoformat() if event_at else None
            entry = flow_by_stage.setdefault(
                stage_id,
                {
                    "issued_qty": 0.0,
                    "issued_last_at": None,
                    "issued_last_dt": None,
                    "accounted_good_qty": 0.0,
                    "accounted_reject_qty": 0.0,
                    "accounted_total_qty": 0.0,
                    "accounted_last_at": None,
                    "accounted_last_dt": None,
                    "sent_qty": 0.0,
                    "sent_last_at": None,
                    "sent_last_dt": None,
                    "accepted_by_next_qty": 0.0,
                    "accepted_by_next_last_at": None,
                    "accepted_by_next_last_dt": None,
                    "flow_events": [],
                },
            )
            entry["accepted_by_next_qty"] += accepted_qty
            if entry["accepted_by_next_last_dt"] is None or (event_at and event_at >= entry["accepted_by_next_last_dt"]):
                entry["accepted_by_next_last_dt"] = event_at
                entry["accepted_by_next_last_at"] = event_at_iso

            existing_transfer_event = next(
                (
                    event
                    for event in entry["flow_events"]
                    if event.get("step") == "transfer" and event.get("transfer_id") == row.transfer_id
                ),
                None,
            )
            transfer_from_name = section_name_by_id.get(row.from_section_id)
            transfer_to_name = section_name_by_id.get(row.to_section_id)
            if existing_transfer_event is not None:
                if is_manual_route_pass:
                    existing_transfer_event["label"] = "Ручной пропуск: передача на след. этап"
                    existing_transfer_event["manual_route_pass"] = True
                if not existing_transfer_event.get("from_section_name"):
                    existing_transfer_event["from_section_name"] = transfer_from_name
                if not existing_transfer_event.get("to_section_name"):
                    existing_transfer_event["to_section_name"] = transfer_to_name
                continue

            entry["flow_events"].append(
                {
                    "step": "transfer",
                    "label": "Ручной пропуск: передача на след. этап" if is_manual_route_pass else "Передача на след. этап",
                    "quantity": round(accepted_qty, 3),
                    "event_at": event_at_iso,
                    "task_id": row.from_task_id,
                    "transfer_id": row.transfer_id,
                    "from_section_name": transfer_from_name,
                    "to_section_name": transfer_to_name,
                    "manual_route_pass": is_manual_route_pass,
                    "_sort_dt": event_at or row.created_at,
                    "_sort_id": row.transfer_id,
                }
            )

        # Build route_snapshot steps
        snapshot_steps = []
        for stage, section in stages:
            op_code = _resolve_stage_operation_code(stage)
            op_name = _resolve_stage_operation_name(stage, operation_names_by_key)
            snapshot_steps.append({
                "route_stage_id": stage.id,
                "sequence": stage.sequence,
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "section_kind": section.type,
                "section_icon": section.icon,
                "section_icon_color": section.icon_color,
                "operation_code": op_code,
                "operation_name": op_name,
            })

        route_snapshot = {
            "route_id": route_info.route_id,
            "route_name": route_info.route_name,
            "route_source": route_info.source,
            "route_origin": route_info.route_origin,
            "route_match_quality": route_info.route_match_quality,
            "route_match_reason": route_info.route_match_reason,
            "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
            "route_manual_confirmed_at": (
                route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
            ),
            "steps": snapshot_steps,
        }

        for stage, section in stages:
            fallback_planned = _to_float(pos.quantity) if not has_tasks else 0.0
            planned_quantity = planned_by_stage.get(stage.id, fallback_planned)
            completed_quantity = task_aggregates_by_stage.get(stage.id, {}).get("completed_quantity", 0.0)
            transferred_quantity = task_aggregates_by_stage.get(stage.id, {}).get("transferred_quantity", 0.0)
            rejected_quantity = task_aggregates_by_stage.get(stage.id, {}).get("rejected_quantity", 0.0)
            task_status = _summarize_task_status(task_statuses_by_stage.get(stage.id, []))
            
            flow = flow_by_stage.get(stage.id, {})
            flow_events = list(flow.get("flow_events", []))
            flow_events.sort(
                key=lambda item: (
                    item.get("_sort_dt") is None,
                    item.get("_sort_dt"),
                    item.get("_sort_id") or 0,
                )
            )

            op_code = _resolve_stage_operation_code(stage)
            op_name = _resolve_stage_operation_name(stage, operation_names_by_key)

            steps_data.append(
                {
                    "route_stage_id": stage.id,
                    "section_id": section.id,
                    "section_code": section.code,
                    "section_name": section.name,
                    "section_icon": section.icon,
                    "section_icon_color": section.icon_color,
                    "sequence": stage.sequence,
                    "operation_code": op_code,
                    "operation_name": op_name,
                    "planned_quantity": round(planned_quantity, 3),
                    "completed_quantity": round(completed_quantity, 3),
                    "transferred_quantity": round(transferred_quantity, 3),
                    "rejected_quantity": round(rejected_quantity, 3),
                    "execution_percent": _clamp_percent(completed_quantity, planned_quantity),
                    "transfer_percent": _clamp_percent(transferred_quantity, planned_quantity),
                    "reject_percent": _clamp_percent(rejected_quantity, planned_quantity),
                    "task_status": task_status,
                    "not_started": not has_tasks,
                    "issued_qty": round(_to_float(flow.get("issued_qty")), 3),
                    "issued_last_at": flow.get("issued_last_at"),
                    "accounted_good_qty": round(_to_float(flow.get("accounted_good_qty")), 3),
                    "accounted_reject_qty": round(_to_float(flow.get("accounted_reject_qty")), 3),
                    "accounted_total_qty": round(_to_float(flow.get("accounted_total_qty")), 3),
                    "accounted_last_at": flow.get("accounted_last_at"),
                    "sent_qty": round(_to_float(flow.get("sent_qty")), 3),
                    "sent_last_at": flow.get("sent_last_at"),
                    "accepted_by_next_qty": round(_to_float(flow.get("accepted_by_next_qty")), 3),
                    "accepted_by_next_last_at": flow.get("accepted_by_next_last_at"),
                    "flow_events": [
                        {
                            "step": event["step"],
                            "label": event["label"],
                            "quantity": event["quantity"],
                            "event_at": event["event_at"],
                            "task_id": event["task_id"],
                            "transfer_id": event["transfer_id"],
                            "from_section_name": event.get("from_section_name"),
                            "to_section_name": event.get("to_section_name"),
                            "manual_route_pass": bool(event.get("manual_route_pass")),
                        }
                        for event in flow_events
                    ],
                }
            )

    # Determine current active stage
    current_stage_info: dict | None = None
    if has_tasks:
        # First try to find in_progress or ready tasks
        current_stage_row = (
            await db.execute(
                select(
                    RouteStage.section_id,
                    RouteStage.sequence,
                    Section.code.label("section_code"),
                    Section.name.label("section_name"),
                    WorkTask.status.label("task_status"),
                    RouteStage.id.label("stage_id"),
                )
                .join(SectionPlanLine, SectionPlanLine.route_stage_id == RouteStage.id)
                .join(Section, Section.id == RouteStage.section_id)
                .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                .where(SectionPlanLine.plan_position_id == pos.id)
                .where(WorkTask.status.in_([WorkTaskStatus.in_progress, WorkTaskStatus.ready]))
                .order_by(
                    WorkTask.status.desc(),
                    RouteStage.sequence,
                )
                .limit(1)
            )
        ).first()

        # Fallback: if no in_progress/ready, pick first non-terminal stage; else last stage.
        if not current_stage_row:
            fallback_stage_rows = (
                await db.execute(
                    select(
                        RouteStage.section_id,
                        RouteStage.sequence,
                        Section.code.label("section_code"),
                        Section.name.label("section_name"),
                        WorkTask.status.label("task_status"),
                        RouteStage.id.label("stage_id"),
                    )
                    .join(SectionPlanLine, SectionPlanLine.route_stage_id == RouteStage.id)
                    .join(Section, Section.id == RouteStage.section_id)
                    .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
                    .where(SectionPlanLine.plan_position_id == pos.id)
                    .order_by(RouteStage.sequence)
                )
            ).all()
            for row in fallback_stage_rows:
                status_value = row.task_status.value if hasattr(row.task_status, "value") else str(row.task_status)
                if status_value not in {"completed", "cancelled"}:
                    current_stage_row = row
                    break
            if not current_stage_row and fallback_stage_rows:
                current_stage_row = fallback_stage_rows[-1]

        if current_stage_row:
            stage = await _get_stage_with_operations(db, current_stage_row.stage_id)
            resolved_op_name = _resolve_stage_operation_name(stage, operation_names_by_key) if stage else ""
            current_stage_info = {
                "current_stage_section_id": current_stage_row.section_id,
                "current_stage_sequence": current_stage_row.sequence,
                "current_stage_operation": resolved_op_name,
                "current_stage_section_code": current_stage_row.section_code,
                "current_stage_section_name": current_stage_row.section_name,
                "current_stage_task_status": (
                    current_stage_row.task_status.value
                    if hasattr(current_stage_row.task_status, "value")
                    else str(current_stage_row.task_status)
                ),
            }

    # Подсчёт доступных остатков ГХП по тем же правилам prefix-match,
    # что и в list_production_planning_rows.
    available_remainder_quantity: float = 0.0
    if route_info.route_id is not None and stages:
        route_remainder_steps: list[dict] = [
            {
                "sequence": stage.sequence,
                "section_id": section.id,
                "operation_codes": {op.operation_code for op in (stage.operations or [])},
            }
            for stage, section in stages
        ]
        effective_product_id = await _resolve_effective_product_id(db, pos)
        from app.services.position_remainders import compute_available_remainder_quantity
        available_remainder_quantity = await compute_available_remainder_quantity(
            db,
            effective_product_id=effective_product_id,
            route_steps=route_remainder_steps,
            position_id=pos.id,
        )

    return {
        "plan_position_id": pos.id,
        "production_plan_id": pos.production_plan_id,
        "source_row_number": pos.source_row_number,
        "source_sku": pos.source_sku,
        "source_name": pos.source_name,
        "quantity": _to_float(pos.quantity),
        "position_status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
        "validation_status": pos.validation_status.value if hasattr(pos.validation_status, "value") else str(pos.validation_status),
        "route_id": route_info.route_id,
        "route_name": route_info.route_name,
        "route_source": route_info.source,
        "route_origin": route_info.route_origin,
        "route_match_quality": route_info.route_match_quality,
        "route_match_reason": route_info.route_match_reason,
        "route_assigned_at": route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
        "route_manual_confirmed_at": (
            route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
        ),
        "route_error": _resolved_route_error(route_info),
        "is_released": bool(has_tasks or pos.status == PlanPositionStatus.released),
        "has_tasks": has_tasks,
        "not_started": not has_tasks,
        "route_snapshot": route_snapshot,
        "stages": steps_data,
        "current_stage_section_id": current_stage_info.get("current_stage_section_id") if current_stage_info else None,
        "current_stage_sequence": current_stage_info.get("current_stage_sequence") if current_stage_info else None,
        "current_stage_operation": current_stage_info.get("current_stage_operation") if current_stage_info else None,
        "current_stage_section_code": current_stage_info.get("current_stage_section_code") if current_stage_info else None,
        "current_stage_section_name": current_stage_info.get("current_stage_section_name") if current_stage_info else None,
        "current_stage_task_status": current_stage_info.get("current_stage_task_status") if current_stage_info else None,
        "available_remainder_quantity": round(available_remainder_quantity, 3),
        "raw_excel_row": (pos.source_payload or {}).get("raw_excel_row"),
        "payload": pos.source_payload,
        "status_history": await _load_position_status_history(db, pos.id),
    }
