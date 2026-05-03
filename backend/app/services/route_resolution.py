from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteStepSignature:
    step_id: str
    operation_code: str | None = None
    section_kind: str | None = None
    description: str = ""


@dataclass
class ResolvedRouteSignature:
    steps: list[RouteStepSignature] = field(default_factory=list)
    primary_operation: str | None = None
    output_kind: str | None = None
    additional_pack_operations: list[str] = field(default_factory=list)


def resolve_route_signature(source_payload: dict[str, Any]) -> ResolvedRouteSignature:
    operation_code = source_payload.get("operation_code")
    output_kind = source_payload.get("output_kind")
    additional_pack = source_payload.get("additional_pack_operations") or []
    additional_codes = [op["operation_code"] for op in additional_pack if "operation_code" in op]

    steps: list[RouteStepSignature] = [
        RouteStepSignature(step_id="WH/ISSUE_RAW", operation_code="ISSUE_RAW", section_kind="raw_stock", description="Выдача сырья"),
    ]

    # Primary operation
    if operation_code in ("DRILL", "PRESS_WINDOW", "PRESS_COMB"):
        steps.append(
            RouteStepSignature(
                step_id=operation_code,
                operation_code=operation_code,
                section_kind="production",
                description="Первичная операция",
            )
        )

    # SHOT is always included by default
    steps.append(RouteStepSignature(step_id="SHOT", operation_code="SHOT", section_kind="production", description="Дробеструй"))

    # ANOD
    steps.append(RouteStepSignature(step_id="ANOD", operation_code="ANOD", section_kind="production", description="Анодирование"))

    # Branch after ANOD
    if output_kind == "semi_finished_shipment":
        steps.append(
            RouteStepSignature(
                step_id="FG_WH/ACCEPT_FINISHED",
                operation_code="ACCEPT_FINISHED",
                section_kind="finished_stock",
                description="Приемка на склад ГП",
            )
        )
    elif output_kind == "finished_good":
        steps.append(
            RouteStepSignature(
                step_id="WIP_WH/MOVE_TO_WIP",
                operation_code="MOVE_TO_WIP",
                section_kind="wip_stock",
                description="Перемещение на промежуточный склад",
            )
        )
        steps.append(RouteStepSignature(step_id="SAW", operation_code="SAW", section_kind="production", description="Пила"))
        steps.append(RouteStepSignature(step_id="PACK", operation_code="PACK", section_kind="production", description="Упаковка"))

        steps.append(
            RouteStepSignature(
                step_id="FG_WH/ACCEPT_FINISHED",
                operation_code="ACCEPT_FINISHED",
                section_kind="finished_stock",
                description="Приемка на склад ГП",
            )
        )

    return ResolvedRouteSignature(
        steps=steps,
        primary_operation=operation_code,
        output_kind=output_kind,
        additional_pack_operations=additional_codes,
    )
