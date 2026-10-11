"""Одно представление задания на доске участка (ADR-0031, тикет #319).

Форма строки доски объявлена здесь ровно один раз — TypedDict'ами
``SectionBoardTaskOut`` (группировочные поля — базовый ``SourceSignature``) —
и собирается ровно одной функцией :func:`build_board_task_row`. Ни
``queries_sections``, ни ``queries_details`` словарь задания сами не собирают:
первый готовит :class:`BoardRowContext` страницы доски, второй берёт ту же
строку и выражает отличие своей формы пост-полями
(:func:`build_task_details_payload`).

Принципы формы (унаследованы от ``schemas/shopfloor.py``, который эту форму
описывал, но не использовался ни одним импортом):

* количества — ``str`` (строковое представление ``Decimal``): JSON не умеет в
  ``Decimal``, а ``float`` теряет точность;
* ``source_payload`` — ``dict``, а не типизированный объект: содержимое
  зависит от операции и задаётся при создании позиции плана;
* вычисленных агрегатов (``totalQtyPlan`` и т.п.) в строке нет — агрегация
  при группировке на фронтенде.

Контракт обязательных ключей защищён сторожем
``tests/test_shopfloor_board_row_contract.py``: набор ключей выводится из
``__required_keys__`` этих TypedDict'ов, поэтому удаление ключа из builder'а
ломает тест.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypedDict

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import format_cut_layout, format_quantity
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.route import RouteStage, SectionOperation
from app.models.work_task import WorkTask
from app.services.plan_position_hanger import resolve_positions_hanger

from .cache import _compute_available_from_balances
from .common import _to_decimal
from .operations_transform import TransformProgress
from .output_rows import build_output_rows

# ---------------------------------------------------------------------------
# Форма строки доски
# ---------------------------------------------------------------------------


class SourceSignature(TypedDict):
    """Группировочные поля задания: чем одно задание отличается от другого.

    Ровно те поля, по которым фронт принимает решение о группировке
    (``features/sections/lib/taskView.ts``): артикул входа/выхода, операция,
    ссылка на строку плана и её сигнатура.
    """

    input_sku: str
    output_sku: str
    display_sku: str
    operation_code: str | None
    operation_name: str | None
    is_significant: bool
    source_ref: str | None
    source_payload: dict[str, Any]
    source_fingerprint: str


class TaskCacheOut(TypedDict):
    """Проекция ledger по заданию (Этап 4): количества — строки Decimal."""

    available_quantity: str
    issued_quantity: str
    completed_quantity: str
    transferred_quantity: str
    received_quantity: str
    rejected_quantity: str
    remaining_quantity: str


class RouteOperationOut(TypedDict):
    """Одна операция в истории маршрута задания."""

    operation_code: str
    operation_name: str
    is_significant: bool
    icon: str | None
    icon_color: str | None


class PreviousStageOut(TypedDict):
    """Проекция строки участка предыдущего этапа."""

    section_plan_line_id: int
    completed_quantity: str
    transferred_quantity: str
    received_quantity: str


class OutputProgressOut(TypedDict):
    """Прогресс по одному выходу трансформирующего этапа (ADR-0002)."""

    row_number: int | None
    dimensions: dict[str, Any] | None
    quantity: str
    produced_quantity: str
    transferred_quantity: str


class SectionBoardTaskOut(SourceSignature):
    """Одна задача на доске участка — контракт ``GET /sections/{id}/board``."""

    id: int
    section_id: int
    product_id: int
    product_sku: str
    section_plan_line_id: int
    plan_position_id: int | None
    route_step_id: int
    sequence: int
    icon: str | None
    icon_color: str | None
    planned_quantity: str
    status: str
    in_daily_plan: bool
    cache: TaskCacheOut
    previous_stage: PreviousStageOut | None
    next_task_id: int | None
    next_task_status: str | None
    next_operation_name: str | None
    dimensions: dict[str, Any] | None
    route_history: list[RouteOperationOut]
    route_history_after: list[RouteOperationOut]
    route_history_full: list[RouteOperationOut]
    route_history_after_full: list[RouteOperationOut]
    operation_codes: list[str | None]
    quantity_per_hanger: int | None
    hanger_count: int | None
    operation_names: list[str]
    transforms_dimensions: bool
    input_quantity: str | None
    input_dimensions: dict[str, Any] | None
    outputs: list[dict[str, Any]]
    cut_layout: dict[str, Any] | None
    outputs_progress: list[OutputProgressOut] | None
    input_consumed_quantity: str | None


# ---------------------------------------------------------------------------
# Контекст страницы доски
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardRowContext:
    """Справочники, общие для всех строк одного ответа доски.

    Батчевая загрузка (fix N+1, #293) вынесена из запроса доски сюда, чтобы
    тем же набором запросов пользовалась ручка задания: строка строится
    одним и тем же кодом на одном и том же контексте.
    """

    op_name_by_section: dict[int, dict[str, str]]
    icon_by_section_op: dict[tuple[int, str], dict[str, Any]]
    section_ops: list[SectionOperation]
    stages_by_route: dict[int, list[RouteStage]]
    stage_by_id: dict[int, RouteStage]
    lines_by_pos_seq: dict[tuple[int, int], SectionPlanLine]
    lines_by_id: dict[int, SectionPlanLine]
    tasks_by_line: dict[int, WorkTask]
    position_by_id: dict[int, PlanPosition]
    hanger_values: dict[int, Any]
    tasks_cache: dict[int, dict[str, Any]]
    transform_progress_map: dict[int, TransformProgress]
    transferred_by_task: dict[int, Any]

    @classmethod
    async def load(
        cls,
        db: AsyncSession,
        *,
        tasks: list[WorkTask],
        section_id: int,
        lines: list[SectionPlanLine] | None = None,
    ) -> BoardRowContext:
        """Собрать контекст для переданных заданий.

        ``lines`` — строки участка, уже прочитанные запросом доски. Без них
        (ручка задания) собственные строки заданий читаются одним запросом;
        набор остальных запросов при этом тот же.
        """
        if lines is None:
            lines = list(
                (
                    await db.execute(
                        select(SectionPlanLine).where(
                            SectionPlanLine.id.in_(
                                {task.section_plan_line_id for task in tasks}
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )

        route_ids = {line.route_id for line in lines}
        plan_position_ids = {line.plan_position_id for line in lines}
        stage_ids = {task.route_stage_id for task in tasks}

        all_stages = list(
            (
                await db.execute(
                    select(RouteStage).where(
                        or_(
                            RouteStage.route_id.in_(route_ids),
                            RouteStage.id.in_(stage_ids),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        stages_by_route: dict[int, list[RouteStage]] = {}
        for stage in all_stages:
            stages_by_route.setdefault(stage.route_id, []).append(stage)
        stage_by_id = {stage.id: stage for stage in all_stages}

        # Все строки участков задействованных позиций: по ним ищутся
        # предыдущая/следующая строка маршрута (prev/next).
        all_lines = list(
            (
                await db.execute(
                    select(SectionPlanLine).where(
                        SectionPlanLine.plan_position_id.in_(plan_position_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        lines_by_pos_seq = {
            (line.plan_position_id, line.sequence): line for line in all_lines
        }
        lines_by_id = {line.id: line for line in all_lines}

        all_positions = list(
            (
                await db.execute(
                    select(PlanPosition).where(PlanPosition.id.in_(plan_position_ids))
                )
            )
            .scalars()
            .all()
        )
        position_by_id = {position.id: position for position in all_positions}
        hanger_values = await resolve_positions_hanger(db, all_positions)

        # Задания всех строк — для next_task_id/статуса и имени операции
        # следующей строки; на строку берётся последнее задание (старший id).
        all_tasks = list(
            (
                await db.execute(
                    select(WorkTask).where(
                        WorkTask.section_plan_line_id.in_(
                            [line.id for line in all_lines]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        tasks_by_line: dict[int, WorkTask] = {}
        for task in all_tasks:
            existing = tasks_by_line.get(task.section_plan_line_id)
            if existing is None or task.id > existing.id:
                tasks_by_line[task.section_plan_line_id] = task

        # Операции участков, задействованных маршрутом, + текущий участок
        # (для справочника операций доски).
        all_section_ids = {stage.section_id for stage in all_stages}
        all_section_ids.add(section_id)
        section_ops = list(
            (
                await db.execute(
                    select(SectionOperation)
                    .where(SectionOperation.section_id.in_(all_section_ids))
                    .order_by(SectionOperation.operation_code)
                )
            )
            .scalars()
            .all()
        )
        op_name_by_section: dict[int, dict[str, str]] = {}
        icon_by_section_op: dict[tuple[int, str], dict[str, Any]] = {}
        for op in section_ops:
            op_name_by_section.setdefault(op.section_id, {})[op.operation_code] = (
                op.operation_name
            )
            if op.icon or op.icon_color:
                icon_by_section_op[(op.section_id, op.operation_code)] = {
                    "icon": op.icon,
                    "icon_color": op.icon_color,
                }

        from app.stock.services import StockProjectionManager

        # tasks и lines уже в этой сессии — передаём их, чтобы bulk не читал
        # те же строки повторным SELECT (identity map, backend/AGENTS.md).
        tasks_cache = await StockProjectionManager().get_tasks_cache_bulk(
            db, [task.id for task in tasks], tasks=tasks, lines=lines
        )

        # Прогресс нужен доске дважды: карточкам (выходы) и синхронизации
        # статусов. Второй поток смотрит на `input_quantity`+`outputs`, а не на
        # маркер этапа, поэтому множество id — объединение предикатов (#293).
        from .operations_transform import (
            get_transferred_by_task_dimensions_bulk,
            get_transform_progress_bulk,
        )

        transform_task_ids = [
            task.id
            for task in tasks
            if (task.outputs or [])
            and (stage_by_id[task.route_stage_id].transforms_dimensions or task.input_quantity is not None)
        ]
        transform_progress_map = await get_transform_progress_bulk(
            db, transform_task_ids
        )
        # Нетто-переданное по каждому габариту трансформирующих заданий —
        # для учётной колонки «Передано» строки «Сдачи» плана (#95).
        transferred_by_task = await get_transferred_by_task_dimensions_bulk(
            db, transform_task_ids
        )

        return cls(
            op_name_by_section=op_name_by_section,
            icon_by_section_op=icon_by_section_op,
            section_ops=section_ops,
            stages_by_route=stages_by_route,
            stage_by_id=stage_by_id,
            lines_by_pos_seq=lines_by_pos_seq,
            lines_by_id=lines_by_id,
            tasks_by_line=tasks_by_line,
            position_by_id=position_by_id,
            hanger_values=hanger_values,
            tasks_cache=tasks_cache,
            transform_progress_map=transform_progress_map,
            transferred_by_task=transferred_by_task,
        )


def _compute_fingerprint(
    source_sku: str | None,
    output_sku: str | None,
    operation_code: str | None,
    source_payload: dict | None,
) -> str:
    """SHA-256 сигнатуры строки доски: артикулы + операция + payload позиции."""
    payload = {
        "input_sku": source_sku or "",
        "output_sku": output_sku or "",
        "operation_code": operation_code or "",
        **(source_payload or {}),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _effective_operation_code(
    task: WorkTask,
    stage: RouteStage,
    source_payload: dict[str, Any] | None,
    ctx: BoardRowContext,
) -> str | None:
    """Код операции задания по приоритету: выбор задания → payload → этап.

    Выбор оператора важнее импорта: ``selected_operation_code`` проставляет
    человек на доске (#319 — та же логика, что была в цикле доски).
    """
    if task.selected_operation_code:
        return task.selected_operation_code
    src_op = (source_payload or {}).get("operation_code")
    if src_op and src_op in ctx.op_name_by_section.get(task.section_id, {}):
        return src_op
    return stage.operations[0].operation_code if stage.operations else None


def _is_significant_operation(
    section_id: int, operation_code: str | None, ctx: BoardRowContext
) -> bool:
    """Признак значимости операции участка (для «пройденных операций»)."""
    for op in ctx.section_ops:
        if op.section_id == section_id and op.operation_code == operation_code:
            return op.is_significant
    return False


def _route_history(
    stage: RouteStage, line: SectionPlanLine, ctx: BoardRowContext
) -> tuple[list[RouteOperationOut], list[RouteOperationOut]]:
    """История маршрута до текущего этапа: (значимые, полная).

    Каждая операция — строка доски со своим ``selected_operation_code`` и
    подписью из справочника участка; для этапа без задания берётся операция
    маршрута.
    """
    route_history: list[RouteOperationOut] = []
    route_history_full: list[RouteOperationOut] = []
    for s in ctx.stages_by_route.get(line.route_id, []):
        if s.sequence >= stage.sequence:
            continue
        prev_line = ctx.lines_by_pos_seq.get((line.plan_position_id, s.sequence))
        prev_work_task = ctx.tasks_by_line.get(prev_line.id) if prev_line else None

        if prev_work_task:
            prev_position = (
                ctx.position_by_id.get(prev_line.plan_position_id) if prev_line else None
            )
            prev_source_payload = (
                (prev_position.source_payload or {}) if prev_position else {}
            )
            prev_eff_op_code = _effective_operation_code(
                prev_work_task, s, prev_source_payload, ctx
            )
            prev_primary_op_name = s.operations[0].operation_name if s.operations else ""
            prev_op_name = (
                ctx.op_name_by_section.get(s.section_id, {}).get(prev_eff_op_code)
                or prev_primary_op_name
            )
            prev_is_significant = _is_significant_operation(
                s.section_id, prev_eff_op_code, ctx
            )
            prev_icon = ctx.icon_by_section_op.get((s.section_id, prev_eff_op_code))
        else:
            prev_eff_op_code = s.operations[0].operation_code if s.operations else None
            prev_op_name = s.operations[0].operation_name if s.operations else ""
            prev_is_significant = _is_significant_operation(
                s.section_id, prev_eff_op_code, ctx
            )
            prev_icon = ctx.icon_by_section_op.get((s.section_id, prev_eff_op_code))

        op_obj: RouteOperationOut = {
            "operation_code": prev_eff_op_code or "",
            "operation_name": prev_op_name,
            "is_significant": prev_is_significant,
            "icon": prev_icon["icon"] if prev_icon else None,
            "icon_color": prev_icon["icon_color"] if prev_icon else None,
        }
        route_history_full.append(op_obj)
        if prev_is_significant:
            route_history.append(op_obj)

    return route_history, route_history_full


def build_board_task_row(
    task: WorkTask,
    line: SectionPlanLine,
    stage: RouteStage,
    *,
    row_sku: str | None,
    source_ref: str | None,
    source_payload: dict[str, Any] | None,
    source_sku: str | None,
    output_sku: str | None,
    in_daily_plan: bool,
    ctx: BoardRowContext,
) -> SectionBoardTaskOut:
    """Собрать одну строку доски — единственная точка сборки формы (ADR-0031).

    ``row_sku``/``source_*``/``in_daily_plan`` — колонки проекции доски,
    которых нет в :class:`BoardRowContext` (они приходят из SQL-запроса).
    """
    effective_op_code = _effective_operation_code(task, stage, source_payload, ctx)
    stage_primary_op_name = stage.operations[0].operation_name if stage.operations else ""
    effective_op_name = (
        ctx.op_name_by_section.get(task.section_id, {}).get(effective_op_code)
        or stage_primary_op_name
    )
    effective_is_significant = _is_significant_operation(
        task.section_id, effective_op_code, ctx
    )

    route_history, route_history_full = _route_history(stage, line, ctx)

    if stage.operations and stage.operations[0].operation_code:
        after_op_code = stage.operations[0].operation_code
        after_op_name = stage.operations[0].operation_name
        after_is_significant = effective_is_significant
        after_icon = ctx.icon_by_section_op.get(
            (task.section_id, stage.operations[0].operation_code)
        )
    else:
        after_op_code = effective_op_code or ""
        after_op_name = effective_op_name
        after_is_significant = effective_is_significant
        after_icon = ctx.icon_by_section_op.get((task.section_id, effective_op_code))

    current_op_obj: RouteOperationOut = {
        "operation_code": after_op_code,
        "operation_name": after_op_name,
        "is_significant": after_is_significant,
        "icon": after_icon["icon"] if after_icon else None,
        "icon_color": after_icon["icon_color"] if after_icon else None,
    }
    route_history_after = (
        [*route_history, current_op_obj] if current_op_obj["operation_code"] else route_history
    )
    route_history_after_full = (
        [*route_history_full, current_op_obj]
        if current_op_obj["operation_code"]
        else route_history_full
    )

    prev_stage = next(
        (s for s in ctx.stages_by_route.get(line.route_id, []) if s.sequence == stage.sequence - 1),
        None,
    )
    prev_stage_info: PreviousStageOut | None = None
    if prev_stage:
        prev_line = ctx.lines_by_pos_seq.get((line.plan_position_id, prev_stage.sequence))
        if prev_line:
            prev_stage_info = {
                "section_plan_line_id": prev_line.id,
                "completed_quantity": str(prev_line.cached_completed_quantity),
                "transferred_quantity": str(prev_line.cached_transferred_quantity),
                "received_quantity": str(prev_line.cached_received_quantity),
            }

    next_line = ctx.lines_by_pos_seq.get((line.plan_position_id, stage.sequence + 1))
    next_task_id: int | None = None
    next_task_status: str | None = None
    next_operation_name: str | None = None
    if next_line:
        next_task = ctx.tasks_by_line.get(next_line.id)
        if next_task:
            next_task_id = next_task.id
            next_task_status = next_task.status.value
        next_stage = ctx.stage_by_id.get(next_line.route_stage_id)
        if next_stage:
            next_operation_name = (
                ", ".join(op.operation_name for op in next_stage.operations)
                if next_stage.operations
                else ""
            )

    task_cache = ctx.tasks_cache.get(task.id, {})
    available = _compute_available_from_balances(
        planned_quantity=_to_decimal(task.planned_quantity),
        received_quantity=task_cache.get("received_quantity", Decimal(0)),
        issued_quantity=task_cache.get("issued_quantity", Decimal(0)),
        returned_quantity=task_cache.get("returned_quantity", Decimal(0))
        if "returned_quantity" in task_cache
        else Decimal(0),
        is_first_stage=bool(line.sequence == 1),
    )

    fingerprint = _compute_fingerprint(
        source_sku, output_sku, effective_op_code, source_payload
    )

    is_paired = source_sku and "+" in source_sku
    effective_display_sku = source_sku if is_paired else (row_sku or "")

    op_icon_info = ctx.icon_by_section_op.get((task.section_id, effective_op_code))

    operation_codes: list[str | None] = []
    operation_names: list[str] = []
    if stage.operations:
        for op in stage.operations:
            op_code = op.operation_code
            if not op_code:
                op_code = effective_op_code
            op_name = (
                ctx.op_name_by_section.get(task.section_id, {}).get(op_code)
                or op.operation_name
            )
            operation_codes.append(op_code)
            operation_names.append(op_name)

    # Трансформирующий этап (ADR-0002): одна позиция плана = одна карточка
    # «вход → все выходы»: «2,75 → 0,9×50 + 1,35×100».
    task_outputs = list(task.outputs or [])
    cut_layout = (
        format_cut_layout(task.input_dimensions, task_outputs)
        if stage.transforms_dimensions
        else None
    )

    # Прогресс по каждому выходу и списанный вход для UI пилы.
    # Гейт — по МАРКЕРУ ЭТАПА, а не по наличию задания в карте: карта
    # батча (#293) шире выдачи — в неё входят и задания с `input_quantity`
    # без `transforms_dimensions` (они нужны синхронизации статусов), и без
    # маркера этапа карточка выходов не выдаётся.
    outputs_progress: list[OutputProgressOut] | None = None
    input_consumed_quantity: str | None = None
    if stage.transforms_dimensions and (
        task.id in ctx.transform_progress_map or task_outputs
    ):
        progress = ctx.transform_progress_map.get(task.id)
        produced_by_group = progress.produced_by_group if progress else {}
        rows_by_output = build_output_rows(
            task_outputs,
            produced_by_group,
            ctx.transferred_by_task.get(task.id) or {},
        )
        outputs_progress = [
            {
                "row_number": row.row_number,
                "dimensions": row.dimensions,
                "quantity": format_quantity(row.quantity),
                "produced_quantity": format_quantity(row.produced_quantity),
                # Нетто-переданное по (задача, размер выхода) из ledger —
                # учётная колонка «Передано» строки «Сдачи» плана.
                "transferred_quantity": format_quantity(row.used_quantity),
            }
            for row in rows_by_output
        ]
        input_consumed_quantity = format_quantity(
            progress.consumed_quantity if progress else Decimal(0)
        )

    hanger_position = ctx.position_by_id.get(line.plan_position_id)
    return {
        "id": task.id,
        "section_id": task.section_id,
        "product_id": task.product_id,
        "product_sku": effective_display_sku,
        "section_plan_line_id": line.id,
        "plan_position_id": line.plan_position_id,
        "route_step_id": stage.id,
        "sequence": stage.sequence,
        "operation_code": effective_op_code,
        "operation_name": effective_op_name,
        "is_significant": effective_is_significant,
        "icon": op_icon_info["icon"] if op_icon_info else None,
        "icon_color": op_icon_info["icon_color"] if op_icon_info else None,
        "planned_quantity": str(task.planned_quantity),
        "status": task.status.value,
        # Прямое членство в дневном плане (#301): этого одного булева фронту
        # хватает, чтобы не предлагать занятое задание кандидатом.
        "in_daily_plan": bool(in_daily_plan),
        "cache": {
            "available_quantity": str(available),
            "issued_quantity": str(task_cache.get("issued_quantity", "0")),
            "completed_quantity": str(task_cache.get("completed_quantity", "0")),
            "transferred_quantity": str(task_cache.get("transferred_quantity", "0")),
            "received_quantity": str(task_cache.get("received_quantity", "0")),
            "rejected_quantity": str(task_cache.get("rejected_quantity", "0")),
            "remaining_quantity": str(task_cache.get("remaining_quantity", "0")),
        },
        "previous_stage": prev_stage_info,
        "next_task_id": next_task_id,
        "next_task_status": next_task_status,
        "next_operation_name": next_operation_name,
        "source_ref": source_ref,
        "source_payload": source_payload or {},
        "source_fingerprint": fingerprint,
        # Размер задания (ADR-0001): габарит материала на этом этапе.
        # У трансформирующих этапов вход/выходы уже несут input_dimensions
        # и outputs — здесь только «размер» нетрансформирующего этапа.
        "dimensions": task.dimensions,
        "input_sku": source_sku or "",
        "output_sku": output_sku or "",
        "display_sku": effective_display_sku,
        "route_history": route_history,
        "route_history_after": route_history_after,
        "route_history_full": route_history_full,
        "route_history_after_full": route_history_after_full,
        "operation_codes": operation_codes,
        "quantity_per_hanger": (
            ctx.hanger_values[hanger_position.id].quantity_per_hanger
            if hanger_position
            else None
        ),
        "hanger_count": (
            int(
                (
                    Decimal(task.planned_quantity)
                    / ctx.hanger_values[hanger_position.id].quantity_per_hanger
                ).to_integral_value(rounding="ROUND_CEILING")
            )
            if hanger_position
            and ctx.hanger_values[hanger_position.id].quantity_per_hanger
            else None
        ),
        "operation_names": operation_names,
        # —— трансформация габаритов (ADR-0002) ——
        "transforms_dimensions": stage.transforms_dimensions,
        "input_quantity": format_quantity(task.input_quantity)
        if task.input_quantity is not None
        else None,
        "input_dimensions": task.input_dimensions,
        "outputs": task_outputs,
        "cut_layout": cut_layout,
        "outputs_progress": outputs_progress,
        "input_consumed_quantity": input_consumed_quantity,
    }


# ---------------------------------------------------------------------------
# Форма ручки задания (GET /shopfloor/tasks/{id})
# ---------------------------------------------------------------------------


class RouteStepOut(TypedDict):
    """Этап маршрута в форме ручки задания."""

    id: int | None
    sequence: int | None
    operation_code: str | None
    operation_name: str | None
    is_final: bool | None


class StockTransactionOut(TypedDict):
    """Проводка ledger задания."""

    id: int
    reason: str
    quantity: str
    from_location_id: int | None
    to_location_id: int | None
    transfer_id: int | None
    created_at: str


class TaskDetailsOut(TypedDict):
    """Ответ ручки задания: строка доски, спроецированная пост-полями."""

    id: int
    status: str
    planned_quantity: str
    cache: TaskCacheOut
    route_step: RouteStepOut
    stock_transactions: list[StockTransactionOut]


def build_task_details_payload(
    row: SectionBoardTaskOut,
    *,
    stage: RouteStage | None,
    stock_transactions: list[StockTransactionOut],
) -> TaskDetailsOut:
    """Проекция строки доски в форму ручки задания.

    Отличие формы от доски выражено здесь ровно тремя пост-полями:
    ``route_step`` — вложенный объект (в строке доски этап плоский:
    ``route_step_id``/``sequence``/``operation_code``/``operation_name``);
    ``is_final`` — признак финального этапа, которого в строке доски нет;
    ``stock_transactions`` — проводки задания. Остальные ключи строки доски
    (навигация, история маршрута, трансформация) в ответ ручки не входят:
    это надмножество, а не вторая форма. Операция этапа берётся из
    ``stage.operations``, а не эффективная (как в строке доски) — так эта
    ручка отвечала до сведения форм.
    """
    return {
        "id": row["id"],
        "status": row["status"],
        "planned_quantity": row["planned_quantity"],
        "cache": row["cache"],
        "route_step": {
            "id": stage.id if stage else None,
            "sequence": stage.sequence if stage else None,
            "operation_code": stage.operations[0].operation_code
            if stage and stage.operations
            else None,
            "operation_name": ", ".join(op.operation_name for op in stage.operations)
            if stage and stage.operations
            else None,
            "is_final": stage.is_final if stage else None,
        },
        "stock_transactions": stock_transactions,
    }
