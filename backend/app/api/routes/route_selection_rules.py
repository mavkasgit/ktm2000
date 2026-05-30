from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section

router = APIRouter(prefix="/route-selection-rules", tags=["route-selection-rules"])

RulePhase = Literal["normalize", "route_select", "resolve_operations"]
RuleSource = Literal["excel", "payload", "product", "ctx"]
RuleOperator = Literal["equals", "not_equals", "contains", "not_contains", "in", "not_in", "empty", "not_empty", "regex"]
RuleAction = Literal["require_section", "exclude_section", "set", "add", "remove", "set_operation", "set_operation_by_mapping", "resolve_by_type"]


class RouteSelectionConditionIn(BaseModel):
    source: RuleSource
    field_path: str = ""
    excel_column_index: int | None = None
    excel_column_letter: str | None = None
    excel_header: str | None = None
    operator: RuleOperator
    value: Any = None
    case_sensitive: bool = False


class RouteSelectionActionIn(BaseModel):
    action: RuleAction
    section_id: int | None = None
    section_code: str | None = None
    group_code: str | None = None
    operation_code: str | None = None
    path: str | None = None
    value: Any = None


class RouteSelectionRuleIn(BaseModel):
    code: str | None = None
    name: str
    profile_id: int | None = None
    priority: int = 0
    is_active: bool = True
    phase: RulePhase = "route_select"
    conditions: list[RouteSelectionConditionIn] = []
    actions: list[RouteSelectionActionIn]


class RouteSelectionConditionOut(RouteSelectionConditionIn):
    pass


class RouteSelectionActionOut(BaseModel):
    action: RuleAction
    section_id: int | None = None
    section_code: str | None = None
    section_name: str | None = None
    group_code: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    path: str | None = None
    value: Any = None
    lookup_field: str | None = None
    mapping: list[dict[str, Any]] | None = None


class RouteSelectionRuleOut(BaseModel):
    id: int
    code: str | None = None
    name: str
    profile_id: int | None = None
    profile_code: str | None = None
    profile_name: str | None = None
    priority: int
    is_active: bool
    phase: RulePhase
    conditions: list[RouteSelectionConditionOut]
    actions: list[RouteSelectionActionOut]


@router.get("", response_model=list[RouteSelectionRuleOut])
async def list_route_selection_rules(
    scope: Literal["global", "profile", "all"] = Query("all"),
    profile_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[RouteSelectionRuleOut]:
    stmt = select(RouteSelectionRule)
    if scope == "global":
        stmt = stmt.where(RouteSelectionRule.profile_id.is_(None))
    elif scope == "profile":
        if profile_id is None:
            return []
        stmt = stmt.where(RouteSelectionRule.profile_id == profile_id)
    stmt = stmt.order_by(RouteSelectionRule.priority.desc(), RouteSelectionRule.id.asc())
    rules = (await db.execute(stmt)).scalars().all()
    return [await _rule_out(db, rule) for rule in rules]


@router.post("", response_model=RouteSelectionRuleOut, status_code=status.HTTP_201_CREATED)
async def create_route_selection_rule(payload: RouteSelectionRuleIn, db: AsyncSession = Depends(get_db)) -> RouteSelectionRuleOut:
    await _validate_payload(db, payload)
    if payload.code:
        existing = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == payload.code))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Rule with this code already exists")

    if payload.profile_id is not None:
        profile = await db.get(RouteRuleProfile, payload.profile_id)
        if profile is None:
            raise HTTPException(status_code=400, detail="Invalid profile_id")

    rule = RouteSelectionRule(
        code=_clean_code(payload.code),
        name=payload.name.strip(),
        profile_id=payload.profile_id,
        priority=payload.priority,
        is_active=payload.is_active,
        phase=payload.phase,
        conditions=[condition.model_dump() for condition in payload.conditions],
        actions=[action.model_dump() for action in payload.actions],
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return await _rule_out(db, rule)


@router.put("/{rule_id}", response_model=RouteSelectionRuleOut)
async def update_route_selection_rule(
    rule_id: int,
    payload: RouteSelectionRuleIn,
    db: AsyncSession = Depends(get_db),
) -> RouteSelectionRuleOut:
    rule = await db.get(RouteSelectionRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    await _validate_payload(db, payload)
    clean_code = _clean_code(payload.code)
    if clean_code:
        existing = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == clean_code, RouteSelectionRule.id != rule_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Rule with this code already exists")

    if payload.profile_id is not None:
        profile = await db.get(RouteRuleProfile, payload.profile_id)
        if profile is None:
            raise HTTPException(status_code=400, detail="Invalid profile_id")

    rule.code = clean_code
    rule.name = payload.name.strip()
    rule.profile_id = payload.profile_id
    rule.priority = payload.priority
    rule.is_active = payload.is_active
    rule.phase = payload.phase
    rule.conditions = [condition.model_dump() for condition in payload.conditions]
    rule.actions = [action.model_dump() for action in payload.actions]
    await db.flush()
    await db.refresh(rule)
    return await _rule_out(db, rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_route_selection_rule(rule_id: int, db: AsyncSession = Depends(get_db)) -> None:
    rule = await db.get(RouteSelectionRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.flush()


async def _validate_payload(db: AsyncSession, payload: RouteSelectionRuleIn) -> None:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Rule name is required")
    if not payload.actions:
        raise HTTPException(status_code=400, detail="At least one action is required")
    for condition in payload.conditions:
        has_field = bool(condition.field_path.strip())
        has_excel_binding = (
            condition.excel_column_index is not None
            or bool((condition.excel_header or "").strip())
        )
        if condition.source == "excel":
            if not has_field and not has_excel_binding:
                raise HTTPException(status_code=400, detail="Excel condition must define field_path or explicit excel column binding")
            if condition.excel_column_index is not None and condition.excel_column_index <= 0:
                raise HTTPException(status_code=400, detail="excel_column_index must be positive")
        elif condition.source == "ctx":
            if not has_field:
                raise HTTPException(status_code=400, detail="Context condition field_path is required")
        elif not has_field:
            raise HTTPException(status_code=400, detail="Condition field_path is required")
        if condition.operator in {"equals", "not_equals", "contains", "not_contains", "in", "not_in", "regex"} and condition.value is None:
            raise HTTPException(status_code=400, detail=f"Condition value is required for {condition.operator}")

    section_ids: set[int] = set()
    section_codes: set[str] = set()
    for action in payload.actions:
        if action.action in {"set", "add", "remove"}:
            if not action.path or not action.path.startswith("ctx."):
                raise HTTPException(status_code=400, detail="DSL action path must start with 'ctx.'")
        elif action.action in {"require_section", "exclude_section"}:
            if action.section_id is None:
                raise HTTPException(status_code=400, detail=f"{action.action} requires section_id")
            section_ids.add(action.section_id)
        elif action.action in {"set_operation", "resolve_by_type"}:
            if not action.section_code:
                raise HTTPException(status_code=400, detail=f"{action.action} requires section_code")
            if not action.group_code:
                raise HTTPException(status_code=400, detail=f"{action.action} requires group_code")
            if not action.operation_code:
                raise HTTPException(status_code=400, detail=f"{action.action} requires operation_code")
            section_codes.add(action.section_code)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action type: {action.action}")

    if section_ids:
        count = len((await db.execute(select(Section.id).where(Section.id.in_(section_ids)))).scalars().all())
        if count != len(section_ids):
            raise HTTPException(status_code=400, detail="Action references unknown section")

    if section_codes:
        count = len((await db.execute(select(Section.code).where(Section.code.in_(section_codes)))).scalars().all())
        if count != len(section_codes):
            raise HTTPException(status_code=400, detail="Action references unknown section_code")


async def _rule_out(db: AsyncSession, rule: RouteSelectionRule) -> RouteSelectionRuleOut:
    section_ids = {
        int(action.get("section_id"))
        for action in (rule.actions or [])
        if action.get("section_id") is not None
    }
    sections = {}
    if section_ids:
        rows = (await db.execute(select(Section).where(Section.id.in_(section_ids)))).scalars().all()
        sections = {section.id: section for section in rows}

    # Load section operations for set_operation actions
    from app.models.route import SectionOperation
    section_ops: dict[int, dict[str, str]] = {}  # section_id -> {op_code -> op_name}
    for action in (rule.actions or []):
        sid = action.get("section_id")
        op_code = action.get("operation_code")
        if sid and op_code and sid not in section_ops:
            ops = (await db.execute(
                select(SectionOperation).where(SectionOperation.section_id == sid)
            )).scalars().all()
            section_ops[sid] = {o.operation_code: o.operation_name for o in ops}

    actions = []
    for action in rule.actions or []:
        action_out = {
            "action": action.get("action"),
            "section_id": action.get("section_id"),
            "section_code": action.get("section_code"),
            "group_code": action.get("group_code"),
            "operation_code": action.get("operation_code"),
            "path": action.get("path"),
            "value": action.get("value"),
        }
        section_id = action.get("section_id")
        if section_id is not None:
            section = sections.get(section_id)
            action_out["section_code"] = section.code if section else action_out.get("section_code")
            action_out["section_name"] = section.name if section else None
            # Resolve operation_name
            op_code = action.get("operation_code")
            if op_code and section_id in section_ops:
                action_out["operation_name"] = section_ops[section_id].get(op_code)
        actions.append(RouteSelectionActionOut(**action_out))

    profile_code = None
    profile_name = None
    if rule.profile_id is not None:
        profile = await db.get(RouteRuleProfile, rule.profile_id)
        if profile:
            profile_code = profile.code
            profile_name = profile.name

    return RouteSelectionRuleOut(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        profile_id=rule.profile_id,
        profile_code=profile_code,
        profile_name=profile_name,
        priority=rule.priority,
        is_active=rule.is_active,
        phase=rule.phase,
        conditions=[RouteSelectionConditionOut(**condition) for condition in rule.conditions or []],
        actions=actions,
    )


def _clean_code(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
