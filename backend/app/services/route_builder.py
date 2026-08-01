"""
route_builder.py
================
Динамическая сборка маршрута из профиля и групп операций.

Вместо захаркоженных ProductionRoute + RouteStep, маршрут строится:
1. Из route_sections профиля (порядок участков)
2. Для каждого участка — все группы операций из SectionOperation
3. Все группы участка получают одинаковый sequence (combined execution)

exclude_section правила из route_select фазы применяются к route_sections:
участки которые попали в exclude_section удаляются из списка перед сборкой.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteRuleProfile, SectionOperation
from app.models.section import Section
from app.models.production_plan import PlanPosition
from app.models.product import Product
from app.services.route_name_builder import build_route_name
from app.services.route_selection import (
    apply_normalize_to_payload,
    build_route_rule_context,
    load_selection_rules_for_profile,
    _load_rules_by_phase,
    _evaluate_condition_with_diagnostic,
)


@dataclass
class BuiltRouteStep:
    """Один шаг динамически собранного маршрута."""
    sequence: int
    section_id: int | None
    section_code: str | None
    section_name: str | None
    section_type: str
    stage_kind: str = "production"
    storage_section_id: int | None = None
    group_code: str | None = None
    group_name: str | None = None
    operation_code: str | None = None
    operation_name: str = ""
    is_significant: bool = False
    is_final: bool = False



@dataclass
class BuiltRoute:
    """Полный динамический маршрут."""
    route_sections: list[str] = field(default_factory=list)
    excluded_sections: list[str] = field(default_factory=list)
    steps: list[BuiltRouteStep] = field(default_factory=list)
    error: str | None = None
    name: str = ""


async def build_route_from_profile(
    db: AsyncSession,
    profile: RouteRuleProfile,
    source_payload: dict[str, Any] | None = None,
    position: PlanPosition | None = None,
) -> BuiltRoute:
    """Собрать маршрут динамически из профиля.

    1. Взять route_sections из профиля
    2. Применить exclude_section правила route_select фазы
    3. Для каждого оставшегося участка: загрузить все группы из SectionOperation
    4. Все группы участка получают одинаковый sequence (combined)
    5. Вернуть BuiltRoute со шагами
    """
    route_section_codes = profile.route_sections or []
    if not route_section_codes:
        return BuiltRoute(error="profile_has_no_route_sections")

    # Получить product для правил (например global_product_skip_shot)
    product: Product | None = None
    if position and position.product_id:
        product = await db.get(Product, position.product_id)
    elif source_payload:
        # Try to resolve product from source_payload product_id (preview path)
        payload_product_id = source_payload.get("product_id")
        if payload_product_id:
            product = await db.get(Product, int(payload_product_id))

    await apply_normalize_to_payload(db, profile.id, source_payload, product)

    # Вычислить excluded sections из route_select правил
    excluded_codes = await _compute_excluded_sections(db, profile.id, source_payload, product)

    # Разрешить конкретные операции из resolve_operations правил
    resolved_ops = await _resolve_operations(db, profile.id, source_payload, product)

    # Отфильтровать route_sections
    filtered_section_codes = [c for c in route_section_codes if c not in excluded_codes]
    if not filtered_section_codes:
        return BuiltRoute(
            route_sections=route_section_codes,
            excluded_sections=sorted(excluded_codes),
            error="all_sections_excluded",
        )

    # Загрузить все участки из filtered route_sections
    sections = (await db.execute(
        select(Section)
        .where(Section.code.in_(filtered_section_codes))
        .order_by(Section.sort_order)
    )).scalars().all()
    sections_by_code = {s.code: s for s in sections}

    # Проверить что все участки существуют
    missing = [c for c in filtered_section_codes if c not in sections_by_code]
    if missing:
        return BuiltRoute(
            route_sections=route_section_codes,
            excluded_sections=sorted(excluded_codes),
            error=f"missing_sections: {', '.join(missing)}",
        )

    # Загрузить все SectionOperation для этих участков
    section_ids = [s.id for s in sections]
    all_ops = (await db.execute(
        select(SectionOperation)
        .where(SectionOperation.section_id.in_(section_ids))
        .where(SectionOperation.group_code.isnot(None))  # только операции в группах
        .order_by(SectionOperation.section_id, SectionOperation.sort_order, SectionOperation.operation_code)
    )).scalars().all()

    # Сгруппировать операции по (section_id, group_code)
    ops_by_section_group: dict[tuple[int, str | None], list[SectionOperation]] = {}
    for op in all_ops:
        key = (op.section_id, op.group_code)
        ops_by_section_group.setdefault(key, []).append(op)

    # Строим шаги маршрута
    steps: list[BuiltRouteStep] = []
    sequence = 0

    from app.services.route_storage_classifier import is_storage_section, infer_stage_kind

    for section_code in filtered_section_codes:
        section = sections_by_code[section_code]

        # Если секция — склад (storage), то это transit-этап.
        # У него не может быть реальных операций, только маркер прохода.
        if is_storage_section(section):
            sequence += 1
            steps.append(BuiltRouteStep(
                sequence=sequence,
                section_id=None,
                section_code=section.code,
                section_name=section.name,
                section_type=section.type,
                stage_kind="transit",
                storage_section_id=section.id,
                operation_code=None,
                operation_name=f"Хранение: {section.name}",
                is_significant=False,
                is_final=False,
            ))
            continue

        # Найти все группы для этого участка
        section_groups: dict[str | None, list[SectionOperation]] = {}
        for (sid, gcode), ops in ops_by_section_group.items():
            if sid == section.id:
                section_groups[gcode] = ops

        if not section_groups:
            # Участок без групп — один шаг с первой операцией
            sequence += 1
            first_op = next((op for (sid, _), ops in ops_by_section_group.items() if sid == section.id for op in ops), None)
            if first_op is None:
                # Участок совсем без операций — пропускаем
                continue

            steps.append(BuiltRouteStep(
                sequence=sequence,
                section_id=section.id,
                section_code=section.code,
                section_name=section.name,
                section_type=section.type,
                stage_kind=infer_stage_kind(section=section),
                group_code=first_op.group_code,
                group_name=first_op.group_name,
                operation_code=first_op.operation_code,
                operation_name=first_op.operation_name,
                is_significant=first_op.is_significant,
                is_final=False,

            ))
        else:
            # Участок с группами — каждый шаг получает уникальный sequence
            # combined_op_group связывает шаги одного участка
            
            sorted_groups = sorted(
                section_groups.items(),
                key=lambda item: _group_sort_key(item[0], item[1]),
            )

            for group_code, group_ops in sorted_groups:
                # Если есть resolved operation для этой группы — взять только её
                key = (section_code, group_code)
                resolved_op_code = resolved_ops.get(key)

                if resolved_op_code:
                    # Взять только операцию которая соответствует resolved
                    matched_op = next((op for op in group_ops if op.operation_code == resolved_op_code), None)
                    if matched_op is None:
                        # Resolved op not found in this group - skip this group
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Resolved op {resolved_op_code} not found in group {group_code} of section {section_code}")
                        continue
                    ops_to_add = [matched_op]
                else:
                    # Нет resolved — взять ПЕРВУЮ операцию группы (не все!)
                    ops_to_add = [group_ops[0]] if group_ops else []

                for op in ops_to_add:
                    sequence += 1  # Каждый шаг получает уникальный sequence
                    is_sig = op.is_significant
                    group_name = op.group_name

                    steps.append(BuiltRouteStep(
                        sequence=sequence,
                        section_id=section.id,
                        section_code=section.code,
                        section_name=section.name,
                        section_type=section.type,
                        stage_kind=infer_stage_kind(section=section),
                        group_code=group_code,
                        group_name=group_name,
                        operation_code=op.operation_code,
                        operation_name=op.operation_name,
                        is_significant=is_sig,
                is_final=False,


            ))
    # Mark last step as final (determined by route structure, not section_code)
    if steps:
        steps[-1].is_final = True

    # Phase: resolve_signatures — compute derived values (output_kind, shot_op)
    await _resolve_signatures(db, profile.id, source_payload, product, filtered_section_codes, excluded_codes)

    # Resolve operation names from SectionOperation reference
    resolved_names = await _resolve_operation_names(db, resolved_ops, filtered_section_codes)

    # Assemble template values from resolved names and payload
    name_values = _assemble_name_values(
        resolved_names, filtered_section_codes, source_payload,
    )

    # Generate descriptive name from profile template
    pattern = profile.route_name_pattern or "{output_kind} - {operations}"
    route_name = build_route_name(pattern, name_values, fallback="Универсальный")

    return BuiltRoute(
        route_sections=route_section_codes,
        excluded_sections=sorted(excluded_codes),
        steps=steps,
        name=route_name,
    )


async def _compute_excluded_sections(
    db: AsyncSession,
    profile_id: int | None,
    source_payload: dict[str, Any] | None,
    product: Product | None,
) -> set[str]:
    """Вычислить коды участков которые нужно исключить на основе route_select правил.

    Загружает правила route_select фазы, evaluates conditions,
    и возвращает set[section_code] для exclude_section actions.
    
    Note: Actions store section_id (int), not section_code (string).
    We need to lookup the Section to get its code.
    """
    all_rules = await load_selection_rules_for_profile(db, profile_id=profile_id)
    select_rules = _load_rules_by_phase(all_rules, "route_select")
    context = build_route_rule_context(source_payload, product)

    # Collect section_ids to exclude
    excluded_ids: set[int] = set()

    for rule in select_rules:
        conditions = list(rule.conditions or [])
        conditions_matched = True
        for condition in conditions:
            from app.services.route_selection import _evaluate_condition_with_diagnostic
            matched, _diagnostic = _evaluate_condition_with_diagnostic(context, condition)
            if not matched:
                conditions_matched = False
                break
        if not conditions_matched:
            continue

        for action in rule.actions or []:
            action_kind = str(action.get("action") or "")
            if action_kind in ("exclude_section", "require_section"):
                section_id = action.get("section_id")
                section_code = action.get("section_code")
                resolved_section_id = section_id
                
                # Resolve section_code to ID if needed
                if resolved_section_id is None and section_code is not None:
                    from sqlalchemy import select as sa_select
                    resolved_section_id = await db.scalar(
                        sa_select(Section.id).where(Section.code == section_code).limit(1)
                    )
                
                if resolved_section_id is not None:
                    if action_kind == "exclude_section":
                        excluded_ids.add(int(resolved_section_id))
                    # Note: require_section is handled similarly if needed

    if not excluded_ids:
        return set()

    # Lookup section codes by ID
    sections = (await db.execute(
        select(Section).where(Section.id.in_(excluded_ids))
    )).scalars().all()
    
    return {s.code for s in sections}


async def _resolve_operations(
    db: AsyncSession,
    profile_id: int | None,
    source_payload: dict[str, Any] | None,
    product: Product | None,
) -> dict[tuple[str, str], str]:
    """Вычислить конкретные операции для групп на основе resolve_operations правил.

    Возвращает dict {(section_code, group_code): operation_code}
    """
    all_rules = await load_selection_rules_for_profile(db, profile_id=profile_id)
    resolve_rules = _load_rules_by_phase(all_rules, "resolve_operations")
    context = build_route_rule_context(source_payload, product)

    resolved: dict[tuple[str, str], str] = {}

    for rule in resolve_rules:
        conditions = list(rule.conditions or [])
        conditions_matched = True
        for condition in conditions:
            from app.services.route_selection import _evaluate_condition_with_diagnostic
            matched, _diagnostic = _evaluate_condition_with_diagnostic(context, condition)
            if not matched:
                conditions_matched = False
                break
        if not conditions_matched:
            continue

        for action in rule.actions or []:
            action_kind = str(action.get("action") or "")
            if action_kind == "set_operation":
                section_code = str(action.get("section_code") or "")
                group_code = str(action.get("group_code") or "")
                operation_code = str(action.get("operation_code") or "")
                if section_code and group_code and operation_code:
                    resolved[(section_code, group_code)] = operation_code
            elif action_kind == "set_operation_by_mapping":
                section_code = str(action.get("section_code") or "")
                group_code = str(action.get("group_code") or "")
                lookup_field = str(action.get("lookup_field") or "color")
                mapping = action.get("mapping") or []
                if section_code and group_code and mapping:
                    # Get the actual value from payload
                    actual_value = context.get("payload", {}).get(lookup_field) or ""
                    if isinstance(actual_value, str):
                        actual_lower = actual_value.lower()
                        # Find first matching keyword in mapping
                        for entry in mapping:
                            keyword = str(entry.get("keyword") or "").lower()
                            if keyword and keyword in actual_lower:
                                op_code = str(entry.get("operation_code") or "")
                                if op_code:
                                    resolved[(section_code, group_code)] = op_code
                                    break

    return resolved


def _group_sort_key(
    group_code: str | None,
    ops: list[SectionOperation],
) -> tuple[int, str]:
    """Sort key для групп: sort_order из первой операции, затем group_code."""
    sort_order = ops[0].sort_order if ops else 0
    return (sort_order, group_code or "")


async def _resolve_signatures(
    db: AsyncSession,
    profile_id: int | None,
    source_payload: dict[str, Any] | None,
    product: Product | None,
    included_sections: list[str],
    excluded_sections: set[str],
) -> None:
    """Apply resolve_signatures rules to set derived values (output_kind, shot_op) in payload."""
    if source_payload is None:
        return
    all_rules = await load_selection_rules_for_profile(db, profile_id=profile_id)
    signature_rules = _load_rules_by_phase(all_rules, "resolve_signatures")
    if not signature_rules:
        return

    context = build_route_rule_context(source_payload, product)
    context["ctx"]["included_sections"] = included_sections
    context["ctx"]["excluded_sections"] = list(excluded_sections)

    for rule in signature_rules:
        conditions = list(rule.conditions or [])
        conditions_matched = True
        for condition in conditions:
            matched, _diagnostic = _evaluate_condition_with_diagnostic(context, condition)
            if not matched:
                conditions_matched = False
                break
        if not conditions_matched:
            continue

        for action in rule.actions or []:
            action_kind = str(action.get("action") or "")
            if action_kind == "set_field":
                path = str(action.get("path") or "")
                value = action.get("value")
                if path.startswith("payload."):
                    field = path[len("payload."):]
                    source_payload[field] = value


async def _resolve_operation_names(
    db: AsyncSession,
    resolved_ops: dict[tuple[str, str], str],
    included_section_codes: list[str],
) -> dict[tuple[str, str], str]:
    """Look up operation names from SectionOperation for resolved ops.

    Returns:
        {(section_code, group_code): operation_name} for each resolved op.
    """
    op_codes = list(resolved_ops.values())
    if not op_codes:
        return {}

    rows = (await db.execute(
        select(SectionOperation)
        .where(SectionOperation.operation_code.in_(op_codes))
    )).scalars().all()
    name_by_code = {r.operation_code: r.operation_name for r in rows}

    result: dict[tuple[str, str], str] = {}
    for (section_code, group_code), op_code in resolved_ops.items():
        result[(section_code, group_code)] = name_by_code.get(op_code, "")

    return result


# Mapping from template variable to (section_code, group_code) in resolved_names.
# This is the only place that knows which operations feed which name slots.
_NAME_VAR_MAPPING: dict[str, tuple[str, str]] = {
    "press_op": ("PRESSING", "PRESS"),
    "drill_op": ("DRILLING", "DRILLING"),
    "color": ("ANODIZING", "ANOD"),
    "pack_op": ("ANODIZING", "PACK"),
}


def _assemble_name_values(
    resolved_names: dict[tuple[str, str], str],
    included_sections: list[str],
    payload: dict | None,
) -> dict[str, str]:
    """Assemble template variables for route name from resolved names and payload.

    Payload fields (output_kind, shot_op) are set by resolve_signatures rules.
    Operation display names come from resolved_names via _NAME_VAR_MAPPING.
    """
    payload = payload or {}
    values: dict[str, str] = {}

    # Payload-driven values (set by resolve_signatures seed rules)
    values["output_kind"] = payload.get("output_kind") or ""
    values["shot_op"] = payload.get("shot_op") or ""

    # Operation names from resolved_names, gated by section inclusion
    for var_name, (section_code, group_code) in _NAME_VAR_MAPPING.items():
        if section_code in included_sections:
            values[var_name] = resolved_names.get((section_code, group_code), "")
        else:
            values[var_name] = ""

    # Composite "operations" for default pattern
    ops_parts = [v for k, v in values.items() if k in ("press_op", "drill_op", "color") and v]
    values["operations"] = " - ".join(ops_parts)

    return values


async def build_route_steps_for_release(
    db: AsyncSession,
    profile: RouteRuleProfile,
    source_payload: dict[str, Any] | None = None,
    position: PlanPosition | None = None,
) -> list[dict]:
    """Собрать шаги маршрута в формате для route_snapshot."""
    route = await build_route_from_profile(db, profile, source_payload, position)
    if route.error:
        raise ValueError(f"route_build_error: {route.error}")

    return [
        {
            "sequence": step.sequence,
            "section_id": step.section_id,
            "section_code": step.section_code,
            "section_name": step.section_name,
            "section_type": step.section_type,
            "group_code": step.group_code,
            "group_name": step.group_name,
            "operation_code": step.operation_code,
            "operation_name": step.operation_name,
            "is_significant": step.is_significant,
            "is_final": step.is_final,

        }
        for step in route.steps
    ]
