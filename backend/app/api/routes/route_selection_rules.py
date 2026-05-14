from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import RouteSelectionRule
from app.models.section import Section

router = APIRouter(prefix="/route-selection-rules", tags=["route-selection-rules"])

RuleSource = Literal["excel", "payload", "product"]
RuleOperator = Literal["equals", "not_equals", "contains", "not_contains", "in", "not_in", "empty", "not_empty", "regex"]
RuleAction = Literal["require_section", "exclude_section"]


class RouteSelectionConditionIn(BaseModel):
    source: RuleSource
    field_path: str
    operator: RuleOperator
    value: Any = None
    case_sensitive: bool = False


class RouteSelectionActionIn(BaseModel):
    action: RuleAction
    section_id: int


class RouteSelectionRuleIn(BaseModel):
    code: str | None = None
    name: str
    priority: int = 0
    is_active: bool = True
    conditions: list[RouteSelectionConditionIn] = []
    actions: list[RouteSelectionActionIn]


class RouteSelectionConditionOut(RouteSelectionConditionIn):
    pass


class RouteSelectionActionOut(RouteSelectionActionIn):
    section_code: str | None = None
    section_name: str | None = None


class RouteSelectionRuleOut(BaseModel):
    id: int
    code: str | None = None
    name: str
    priority: int
    is_active: bool
    conditions: list[RouteSelectionConditionOut]
    actions: list[RouteSelectionActionOut]


@router.get("", response_model=list[RouteSelectionRuleOut])
async def list_route_selection_rules(db: AsyncSession = Depends(get_db)) -> list[RouteSelectionRuleOut]:
    rules = (
        await db.execute(select(RouteSelectionRule).order_by(RouteSelectionRule.priority.desc(), RouteSelectionRule.id.asc()))
    ).scalars().all()
    return [await _rule_out(db, rule) for rule in rules]


@router.post("", response_model=RouteSelectionRuleOut, status_code=status.HTTP_201_CREATED)
async def create_route_selection_rule(payload: RouteSelectionRuleIn, db: AsyncSession = Depends(get_db)) -> RouteSelectionRuleOut:
    await _validate_payload(db, payload)
    if payload.code:
        existing = await db.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == payload.code))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Rule with this code already exists")

    rule = RouteSelectionRule(
        code=_clean_code(payload.code),
        name=payload.name.strip(),
        priority=payload.priority,
        is_active=payload.is_active,
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

    rule.code = clean_code
    rule.name = payload.name.strip()
    rule.priority = payload.priority
    rule.is_active = payload.is_active
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
        if not condition.field_path.strip():
            raise HTTPException(status_code=400, detail="Condition field_path is required")
        if condition.operator in {"equals", "not_equals", "contains", "not_contains", "in", "not_in", "regex"} and condition.value is None:
            raise HTTPException(status_code=400, detail=f"Condition value is required for {condition.operator}")
    section_ids = {action.section_id for action in payload.actions}
    count = len((await db.execute(select(Section.id).where(Section.id.in_(section_ids)))).scalars().all())
    if count != len(section_ids):
        raise HTTPException(status_code=400, detail="Action references unknown section")


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
    actions = []
    for action in rule.actions or []:
        section_id = int(action.get("section_id"))
        section = sections.get(section_id)
        actions.append(
            RouteSelectionActionOut(
                action=action.get("action"),
                section_id=section_id,
                section_code=section.code if section else None,
                section_name=section.name if section else None,
            )
        )
    return RouteSelectionRuleOut(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        priority=rule.priority,
        is_active=rule.is_active,
        conditions=[RouteSelectionConditionOut(**condition) for condition in rule.conditions or []],
        actions=actions,
    )


def _clean_code(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
