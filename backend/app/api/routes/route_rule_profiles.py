from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.import_template import ImportTemplate
from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.services.route_builder import build_route_from_profile

router = APIRouter(prefix="/route-rule-profiles", tags=["route-rule-profiles"])


class ExcelColumnPassportItem(BaseModel):
    index: int
    letter: str
    header: str
    field_path: str


class RouteRuleProfileIn(BaseModel):
    code: str
    name: str
    is_active: bool = True
    priority: int = 0
    import_template_id: int | None = None
    excel_column_passport: list[ExcelColumnPassportItem] = Field(default_factory=list)
    excel_passport_meta: dict[str, Any] = Field(default_factory=dict)
    route_sections: list[str] = Field(default_factory=list)


class RouteRuleProfileOut(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool
    priority: int
    import_template_id: int | None = None
    template_code: str | None = None
    template_name: str | None = None
    excel_column_passport: list[ExcelColumnPassportItem] = Field(default_factory=list)
    excel_passport_meta: dict[str, Any] = Field(default_factory=dict)
    route_sections: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


@router.get("", response_model=list[RouteRuleProfileOut])
async def list_route_rule_profiles(db: AsyncSession = Depends(get_db)) -> list[RouteRuleProfileOut]:
    profiles = (
        await db.execute(
            select(RouteRuleProfile).order_by(RouteRuleProfile.priority.desc(), RouteRuleProfile.id.asc())
        )
    ).scalars().all()
    return [await _profile_out(p, db) for p in profiles]


@router.post("", response_model=RouteRuleProfileOut, status_code=status.HTTP_201_CREATED)
async def create_route_rule_profile(
    payload: RouteRuleProfileIn,
    db: AsyncSession = Depends(get_db),
) -> RouteRuleProfileOut:
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Profile code is required")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Profile name is required")

    existing = await db.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == payload.code.strip()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Profile with this code already exists")

    passport, meta = _normalize_passport(payload.excel_column_passport, payload.excel_passport_meta)

    if payload.import_template_id is not None:
        template = await db.get(ImportTemplate, payload.import_template_id)
        if template is None:
            raise HTTPException(status_code=400, detail="Invalid import_template_id")

    profile = RouteRuleProfile(
        code=payload.code.strip(),
        name=payload.name.strip(),
        is_active=payload.is_active,
        priority=payload.priority,
        import_template_id=payload.import_template_id,
        excel_column_passport=passport,
        excel_passport_meta=meta,
        route_sections=payload.route_sections or [],
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return await _profile_out(profile, db)


@router.put("/{profile_id}", response_model=RouteRuleProfileOut)
async def update_route_rule_profile(
    profile_id: int,
    payload: RouteRuleProfileIn,
    db: AsyncSession = Depends(get_db),
) -> RouteRuleProfileOut:
    profile = await db.get(RouteRuleProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    clean_code = payload.code.strip()
    if not clean_code:
        raise HTTPException(status_code=400, detail="Profile code is required")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Profile name is required")

    existing = await db.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == clean_code, RouteRuleProfile.id != profile_id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Profile with this code already exists")

    passport, meta = _normalize_passport(payload.excel_column_passport, payload.excel_passport_meta)

    if payload.import_template_id is not None:
        template = await db.get(ImportTemplate, payload.import_template_id)
        if template is None:
            raise HTTPException(status_code=400, detail="Invalid import_template_id")

    profile.code = clean_code
    profile.name = payload.name.strip()
    profile.is_active = payload.is_active
    profile.priority = payload.priority
    profile.import_template_id = payload.import_template_id
    profile.excel_column_passport = passport
    profile.excel_passport_meta = meta
    profile.route_sections = payload.route_sections or []
    await db.flush()
    await db.refresh(profile)
    return await _profile_out(profile, db)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_route_rule_profile(profile_id: int, db: AsyncSession = Depends(get_db)) -> None:
    profile = await db.get(RouteRuleProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    rule_ref = (
        await db.execute(
            select(RouteSelectionRule.id).where(RouteSelectionRule.profile_id == profile_id).limit(1)
        )
    ).scalars().first()
    if rule_ref is not None:
        raise HTTPException(status_code=409, detail="Cannot delete profile: it is used by route selection rules")

    await db.delete(profile)
    await db.flush()


class RouteStepPreview(BaseModel):
    sequence: int
    section_id: int
    section_code: str
    section_name: str
    section_kind: str
    group_code: str | None = None
    group_name: str | None = None
    operation_code: str | None = None
    operation_name: str = ""
    is_significant: bool = False
    is_final: bool = False
    combined_op_group: str | None = None


class RoutePreviewResponse(BaseModel):
    profile_id: int
    profile_code: str
    profile_name: str
    route_sections: list[str]
    excluded_sections: list[str] = Field(default_factory=list)
    steps: list[RouteStepPreview]
    error: str | None = None


@router.get("/{profile_id}/route-preview", response_model=RoutePreviewResponse)
async def preview_profile_route(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
) -> RoutePreviewResponse:
    """Показать маршрут для выбранного профиля правил.

    Строит динамический маршрут из profile.route_sections, применяет
    exclude_section правила и возвращает итоговые шаги.
    """
    profile = await db.get(RouteRuleProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    if not profile.route_sections:
        raise HTTPException(status_code=400, detail="Profile has no route_sections defined")

    route = await build_route_from_profile(db, profile, source_payload=None, position=None)

    return RoutePreviewResponse(
        profile_id=profile.id,
        profile_code=profile.code,
        profile_name=profile.name,
        route_sections=list(profile.route_sections or []),
        excluded_sections=route.excluded_sections,
        steps=[
            RouteStepPreview(
                sequence=step.sequence,
                section_id=step.section_id,
                section_code=step.section_code,
                section_name=step.section_name,
                section_kind=step.section_kind,
                group_code=step.group_code,
                group_name=step.group_name,
                operation_code=step.operation_code,
                operation_name=step.operation_name,
                is_significant=step.is_significant,
                is_final=step.is_final,
                combined_op_group=step.combined_op_group,
            )
            for step in route.steps
        ],
        error=route.error,
    )


def _normalize_passport(
    passport: list[ExcelColumnPassportItem],
    meta: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for column in passport:
        index = int(column.index)
        if index <= 0:
            raise HTTPException(status_code=400, detail="excel_column_passport.index must be positive")
        if index in seen_indexes:
            raise HTTPException(status_code=400, detail="excel_column_passport has duplicate index values")
        seen_indexes.add(index)

        letter = column.letter.strip().upper()
        header = column.header.strip()
        field_path = column.field_path.strip()
        if not letter:
            raise HTTPException(status_code=400, detail="excel_column_passport.letter is required")
        if not header:
            raise HTTPException(status_code=400, detail="excel_column_passport.header is required")
        if not field_path:
            raise HTTPException(status_code=400, detail="excel_column_passport.field_path is required")

        normalized.append(
            {
                "index": index,
                "letter": letter,
                "header": header,
                "field_path": field_path,
            }
        )

    normalized_meta = dict(meta or {})
    if normalized:
        normalized_meta.setdefault("updated_at", datetime.now(UTC).isoformat())
    return normalized, normalized_meta


async def _profile_out(profile: RouteRuleProfile, db: AsyncSession) -> RouteRuleProfileOut:
    template_code = None
    template_name = None
    if profile.import_template_id is not None:
        template = await db.get(ImportTemplate, profile.import_template_id)
        if template:
            template_code = template.code
            template_name = template.name

    return RouteRuleProfileOut(
        id=profile.id,
        code=profile.code,
        name=profile.name,
        is_active=profile.is_active,
        priority=profile.priority,
        import_template_id=profile.import_template_id,
        template_code=template_code,
        template_name=template_name,
        excel_column_passport=[ExcelColumnPassportItem(**item) for item in (profile.excel_column_passport or [])],
        excel_passport_meta=dict(profile.excel_passport_meta or {}),
        route_sections=list(profile.route_sections or []),
        created_at=profile.created_at,
    )
