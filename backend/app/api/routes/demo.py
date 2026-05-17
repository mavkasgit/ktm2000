from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.internal_plan import SectionPlanLine
from app.models.imports import ImportBatchMode
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanPosition,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.techcard import Techcard
from app.models.user import User
from app.models.work_task import WorkTask
from app.services.plan_generation import create_release_batch, release_batch
from app.services.plan_import_service import create_excel_import_change_set
from app.services.import_normalization import default_import_normalization_rules
from app.services.production_plan_service import apply_change_set, approve_plan_position
from app.services.shopfloor_service import complete_task, issue_to_work, transfer_receive, transfer_send

router = APIRouter(prefix="/demo", tags=["demo"])

THREE_DEC = Decimal("0.001")


class StagePreset(str, Enum):
    before_approve = "before_approve"
    after_approve = "after_approve"
    after_release = "after_release"
    to_step_ready = "to_step_ready"
    full_route = "full_route"


class FullRouteRunRequest(BaseModel):
    initial_quantity: Decimal = Decimal("100")
    route_name: str = "Типовой: полный (все участки)"
    route_id: int | None = None
    techcard_id: int
    production_plan_id: int | None = None
    run_id: str | None = None
    start_performed_at: datetime | None = None
    plan_month: str | None = None
    plan_version: str | None = None
    stage_preset: StagePreset = StagePreset.before_approve
    target_route_step_id: int | None = None
    scenario_id: str | None = None


class StageRunResult(BaseModel):
    section_id: int
    section_code: str
    task_id: int
    input_qty: str
    defect_percent: int
    defect_qty: str
    good_qty: str
    performed_at: str
    accounted_at: str


class FullRouteRunResponse(BaseModel):
    run_id: str
    production_plan_id: int
    plan_position_id: int
    internal_plan_id: int | None
    route_id: int
    tasks_created: int
    stage_preset: str
    stopped_at_stage: str
    stage_results: list[StageRunResult]
    execution_row_url: str
    shopfloor_section_urls: list[str]


def _scenario_map() -> dict[str, dict]:
    scenarios_path = Path(__file__).resolve().parents[3] / "data" / "route_signature_scenarios.json"
    data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    return {item["scenario_id"]: item for item in data}


def _workbook_for_product(
    *,
    sku: str,
    product_name: str,
    quantity: Decimal,
    comments: str,
    operation_raw: str = "",
    output_kind_raw: str = "ГП",
    secondary_sku: str | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
        ]
    )
    qty = float(quantity)
    ws.append(
        [
            sku,
            "ТЗ",
            product_name,
            3400,
            "серебро",
            qty,
            2.7,
            operation_raw,
            "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт",
            "",
            2.7,
            qty,
            qty,
            qty,
            output_kind_raw,
            comments,
        ]
    )
    if secondary_sku:
        # Two-row paired profile import: second row has empty name so parser can join rows.
        ws.append(
            [
                secondary_sku,
                "ТЗ",
                "",
                3400,
                "серебро",
                qty,
                2.7,
                operation_raw,
                "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт",
                "",
                2.7,
                qty,
                qty,
                qty,
                output_kind_raw,
                comments,
            ]
        )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _round_qty(value: Decimal) -> Decimal:
    return value.quantize(THREE_DEC, rounding=ROUND_HALF_UP)


def _defect_percent(sequence: int) -> int:
    return ((sequence * 7 + 3) % 10) + 1


def _compute_defect_qty(input_qty: Decimal, percent: int) -> Decimal:
    if input_qty <= 0:
        return Decimal("0")
    raw = (input_qty * Decimal(percent) / Decimal("100"))
    defect = _round_qty(raw)
    max_defect = max(Decimal("0"), input_qty - THREE_DEC)
    if defect > max_defect:
        defect = max_defect
    if defect < 0:
        defect = Decimal("0")
    return defect


async def _find_position_by_run_id(db: AsyncSession, run_id: str) -> PlanPosition | None:
    position_id = await db.scalar(
        text(
            "SELECT id FROM plan_positions "
            "WHERE source_payload->>'test_run_id' = :run_id "
            "ORDER BY id DESC LIMIT 1"
        ).bindparams(run_id=run_id)
    )
    if position_id is None:
        return None
    return await db.get(PlanPosition, int(position_id))


async def _check_run_id_exists(db: AsyncSession, run_id: str) -> bool:
    """Check if a run with this ID already exists (strict uniqueness)."""
    existing = await _find_position_by_run_id(db, run_id)
    return existing is not None


async def _collect_tasks_for_position(db: AsyncSession, plan_position_id: int) -> list[tuple[WorkTask, SectionPlanLine, RouteStep, Section]]:
    rows = (
        await db.execute(
            select(WorkTask, SectionPlanLine, RouteStep, Section)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .join(RouteStep, WorkTask.route_step_id == RouteStep.id)
            .join(Section, RouteStep.section_id == Section.id)
            .where(SectionPlanLine.plan_position_id == plan_position_id)
            .order_by(RouteStep.sequence, WorkTask.id)
        )
    ).all()
    return rows


@router.post(
    "/test-runs/full-route",
    response_model=FullRouteRunResponse,
)
async def run_full_route_test(
    payload: FullRouteRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FullRouteRunResponse:
    if payload.initial_quantity <= 0:
        raise HTTPException(status_code=400, detail="initial_quantity must be > 0")

    run_id = (payload.run_id or f"run-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}").strip()
    
    # Strict uniqueness: reject duplicate run_id
    if await _check_run_id_exists(db, run_id):
        raise HTTPException(status_code=409, detail=f"run_id '{run_id}' already exists. Each run_id must be unique.")

    # Validate stage_preset requirements
    if payload.stage_preset == StagePreset.to_step_ready and not payload.target_route_step_id:
        raise HTTPException(status_code=400, detail="target_route_step_id is required for 'to_step_ready' preset")

    start_at = payload.start_performed_at or datetime.now(UTC)
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=UTC)

    route: ProductionRoute | None = None
    if payload.route_id is not None:
        route = await db.get(ProductionRoute, payload.route_id)
    if route is None:
        route = await db.scalar(select(ProductionRoute).where(ProductionRoute.name == payload.route_name))
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    if not route.is_active:
        raise HTTPException(status_code=400, detail="Route is inactive")

    techcard = await db.get(Techcard, payload.techcard_id)
    if techcard is None:
        raise HTTPException(status_code=404, detail="Techcard not found")
    if not techcard.is_active:
        raise HTTPException(status_code=400, detail="Techcard is inactive")
    if techcard.product_id is None:
        raise HTTPException(status_code=400, detail="Techcard has no linked product")
    product = await db.get(Product, techcard.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Techcard product not found")

    comments = f"TEST_RUN:{run_id}"
    scenario = None
    if payload.scenario_id:
        scenarios = _scenario_map()
        scenario = scenarios.get(payload.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=400, detail=f"Unknown scenario_id '{payload.scenario_id}'")

    content = _workbook_for_product(
        sku=(scenario or {}).get("primary_sku", product.sku),
        product_name=product.name,
        quantity=payload.initial_quantity,
        comments=comments,
        operation_raw=(scenario or {}).get("operation_raw", ""),
        output_kind_raw=(scenario or {}).get("output_kind_raw", "ГП"),
        secondary_sku=(scenario or {}).get("secondary_sku"),
    )

    target_plan_id = payload.production_plan_id
    if target_plan_id is not None:
        target_plan = await db.get(ProductionPlan, target_plan_id)
        if target_plan is None:
            raise HTTPException(status_code=404, detail="Production plan not found")
        # Demo run should always be executable. If selected plan is closed, fork into a new plan.
        if target_plan.status in {ProductionPlanStatus.released, ProductionPlanStatus.cancelled}:
            target_plan_id = None

    import_result = await create_excel_import_change_set(
        db,
        filename=f"test-{product.sku}-{run_id}.xlsx",
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_index=0,
        production_plan_id=target_plan_id,
        mode=ImportBatchMode.append_to_plan if target_plan_id else ImportBatchMode.create_plan,
        plan_month=payload.plan_month,
        plan_version=payload.plan_version,
        column_mapping=None,
        normalization_rules=default_import_normalization_rules(),
    )

    change_set_id = int(import_result["change_set_id"])
    await apply_change_set(db, change_set_id)

    position_id = await db.scalar(
        select(PlanChangeItem.plan_position_id).where(
            PlanChangeItem.change_set_id == change_set_id,
            PlanChangeItem.change_action.in_(
                [PlanChangeAction.create_position, PlanChangeAction.update_draft_position]
            ),
            PlanChangeItem.plan_position_id.is_not(None),
        ).order_by(PlanChangeItem.id.desc())
    )
    if position_id is None:
        raise HTTPException(status_code=500, detail="No plan position created for test run")

    position = await db.get(PlanPosition, int(position_id))
    if position is None:
        raise HTTPException(status_code=500, detail="Created plan position not found")

    payload_json = dict(position.source_payload or {})
    payload_json["test_run_id"] = run_id
    payload_json["test_route_id"] = route.id
    payload_json["test_techcard_id"] = techcard.id
    position.source_payload = payload_json
    if position.source_name:
        if f"[TEST {run_id}]" not in position.source_name:
            position.source_name = f"{position.source_name} [TEST {run_id}]"
    else:
        position.source_name = f"[TEST {run_id}]"
    position.route_id = route.id
    await db.flush()

    # Stop at before_approve: position created, not approved/released
    if payload.stage_preset == StagePreset.before_approve:
        return FullRouteRunResponse(
            run_id=run_id,
            production_plan_id=position.production_plan_id,
            plan_position_id=position.id,
            internal_plan_id=None,
            route_id=route.id,
            tasks_created=0,
            stage_preset=payload.stage_preset.value,
            stopped_at_stage="import_applied",
            stage_results=[],
            execution_row_url="/execution",
            shopfloor_section_urls=[],
        )

    # Approve the position
    try:
        await approve_plan_position(db, position.production_plan_id, position.id, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Approve failed: {exc}") from exc

    # Stop at after_approve: position approved, not released
    if payload.stage_preset == StagePreset.after_approve:
        return FullRouteRunResponse(
            run_id=run_id,
            production_plan_id=position.production_plan_id,
            plan_position_id=position.id,
            internal_plan_id=None,
            route_id=route.id,
            tasks_created=0,
            stage_preset=payload.stage_preset.value,
            stopped_at_stage="approved",
            stage_results=[],
            execution_row_url="/execution",
            shopfloor_section_urls=[],
        )

    # Release the position (creates tasks)
    try:
        batch_summary = await create_release_batch(
            db,
            production_plan_id=position.production_plan_id,
            positions=[{"plan_position_id": position.id, "release_quantity": str(position.quantity)}],
        )
        release_summary = await release_batch(db, batch_summary["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Release failed: {exc}") from exc

    task_rows = await _collect_tasks_for_position(db, position.id)
    if not task_rows:
        raise HTTPException(status_code=500, detail="No tasks created for released position")

    # Stop at after_release: position released, tasks created, no movements
    if payload.stage_preset == StagePreset.after_release:
        section_urls = [f"/shopfloor-tasks/{row[3].id}" for row in task_rows]
        return FullRouteRunResponse(
            run_id=run_id,
            production_plan_id=position.production_plan_id,
            plan_position_id=position.id,
            internal_plan_id=release_summary.get("internal_plan_id"),
            route_id=route.id,
            tasks_created=len(task_rows),
            stage_preset=payload.stage_preset.value,
            stopped_at_stage="released",
            stage_results=[],
            execution_row_url="/execution",
            shopfloor_section_urls=sorted(set(section_urls)),
        )

    # For to_step_ready: find the target step index
    target_step_index = None
    if payload.stage_preset == StagePreset.to_step_ready:
        target_step_index = None
        for idx, (_task, _line, step, _section) in enumerate(task_rows):
            if step.id == payload.target_route_step_id:
                target_step_index = idx
                break
        if target_step_index is None:
            raise HTTPException(status_code=400, detail="target_route_step_id not found in route steps")

    # Auto-execute steps with early stop for to_step_ready
    stage_results: list[StageRunResult] = []
    section_urls: list[str] = []

    for idx, (task, _line, step, section) in enumerate(task_rows):
        # For to_step_ready: stop before executing the target step (leave it ready)
        if payload.stage_preset == StagePreset.to_step_ready and idx == target_step_index:
            # Target step stays ready, don't execute it
            break

        input_qty = _round_qty(task.planned_quantity if idx == 0 else Decimal(stage_results[-1].good_qty))
        defect_percent = _defect_percent(step.sequence)
        defect_qty = _compute_defect_qty(input_qty, defect_percent)
        good_qty = _round_qty(input_qty - defect_qty)

        performed_at = start_at + timedelta(minutes=idx * 10)
        accounted_at = performed_at + timedelta(minutes=2)
        movement_key = f"{run_id}:step:{step.sequence}"

        try:
            await issue_to_work(
                db,
                task_id=task.id,
                quantity=input_qty,
                actor_id=current_user.id,
                comment=f"demo issue {run_id}",
                source_ref=run_id,
                idempotency_key=f"{movement_key}:issue",
                executor_user_id=current_user.id,
                performed_at=performed_at,
                accounted_at=accounted_at,
            )
            await complete_task(
                db,
                task_id=task.id,
                good_quantity=good_qty,
                defect_quantity=defect_qty,
                actor_id=current_user.id,
                defect_reason="demo_defect",
                comment=f"demo complete {run_id}",
                idempotency_key=f"{movement_key}:complete",
                executor_user_id=current_user.id,
                performed_at=performed_at,
                accounted_at=accounted_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Task execution failed at step {step.sequence}: {exc}") from exc

        # Record the completed stage
        stage_results.append(
            StageRunResult(
                section_id=section.id,
                section_code=section.code,
                task_id=task.id,
                input_qty=str(input_qty),
                defect_percent=defect_percent,
                defect_qty=str(defect_qty),
                good_qty=str(good_qty),
                performed_at=performed_at.isoformat(),
                accounted_at=accounted_at.isoformat(),
            )
        )
        section_urls.append(f"/shopfloor-tasks/{section.id}")

        # For to_step_ready: don't transfer to the target step
        if payload.stage_preset == StagePreset.to_step_ready and (idx + 1) == target_step_index:
            # Stop before transferring to target step
            break

        if idx < len(task_rows) - 1:
            next_task = task_rows[idx + 1][0]
            try:
                transfer_result = await transfer_send(
                    db,
                    from_task_id=task.id,
                    to_task_id=next_task.id,
                    quantity=good_qty,
                    actor_id=current_user.id,
                    comment=f"demo send {run_id}",
                    idempotency_key=f"{movement_key}:send",
                    executor_user_id=current_user.id,
                    performed_at=performed_at,
                    accounted_at=accounted_at,
                )
                await transfer_receive(
                    db,
                    transfer_id=int(transfer_result["transfer_id"]),
                    accepted_quantity=good_qty,
                    rejected_quantity=Decimal("0"),
                    actor_id=current_user.id,
                    reason="demo_accept",
                    comment=f"demo accept {run_id}",
                    idempotency_key=f"{movement_key}:receive",
                    executor_user_id=current_user.id,
                    performed_at=performed_at,
                    accounted_at=accounted_at,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Transfer failed at step {step.sequence}: {exc}") from exc

    stopped_stage = payload.stage_preset.value
    if payload.stage_preset == StagePreset.to_step_ready:
        stopped_stage = f"step_{payload.target_route_step_id}_ready"
    elif payload.stage_preset == StagePreset.full_route:
        stopped_stage = "completed"

    return FullRouteRunResponse(
        run_id=run_id,
        production_plan_id=position.production_plan_id,
        plan_position_id=position.id,
        internal_plan_id=release_summary.get("internal_plan_id"),
        route_id=route.id,
        tasks_created=len(stage_results),
        stage_preset=payload.stage_preset.value,
        stopped_at_stage=stopped_stage,
        stage_results=stage_results,
        execution_row_url="/execution",
        shopfloor_section_urls=sorted(set(section_urls)),
    )
