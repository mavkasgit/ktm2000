from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product
from app.models.imports import ImportBatch
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
)
from app.models.route import ProductionRoute, RouteRuleProfile
from app.services.color_extraction import resolve_payload_color
from app.services.route_builder import build_route_from_profile
from app.services.route_selection import RouteCandidateDiagnostic, select_route_for_payload
from app.services.route_signature import auto_route_code, route_signature_conflicts
from app.services.route_identity import find_route_by_code, find_route_by_name


class RouteSignatureConflict(Exception):
    """Маршрут найден по коду, но его состав разошёлся с пересобранным.

    Код — производная сигнатуры, но ``refresh_route_signature`` код не
    обновляет: маршрут, переписанный руками, сохраняет прежний ``auto-``-код
    и продолжает находиться по нему. Отдельное исключение, а не возврат
    ``None``, потому что ``None`` уводит резолв в ветку сохранённого
    назначения — и позиция выглядела бы назначенной иной маршрут, молча.
    """

    def __init__(self, route_id: int) -> None:
        super().__init__(f"route #{route_id}: сигнатура не совпадает с пересобранной")
        self.route_id = route_id


@dataclass(slots=True)
class ResolvedRouteInfo:
    route_id: int | None
    route_name: str | None
    source: str  # compatibility: "manual" | "auto" | "legacy" | "missing"
    route_origin: str | None = None
    route_match_quality: str | None = None
    route_match_reason: str | None = None
    route_assigned_at: datetime | None = None
    route_manual_confirmed_at: datetime | None = None
    error: str | None = None
    checked_rules: list[int] = field(default_factory=list)
    required_sections: list[dict] = field(default_factory=list)
    excluded_sections: list[dict] = field(default_factory=list)
    candidate_routes: list[RouteCandidateDiagnostic] = field(default_factory=list)
    selected_route_id: int | None = None
    condition_diagnostics: list[dict] = field(default_factory=list)


def _normalize_origin(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteOrigin):
        return value.value
    raw = str(value)
    return raw or None


def _normalize_quality(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteMatchQuality):
        return value.value
    raw = str(value)
    return raw or None


def _normalize_reason(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, PlanPositionRouteMatchReason):
        return value.value
    raw = str(value)
    return raw or None


def _compat_source_from_origin(origin: str | None, route_id: int | None) -> str:
    if route_id is None:
        return "missing"
    if origin == PlanPositionRouteOrigin.manual_confirmed.value:
        return "manual"
    if origin == PlanPositionRouteOrigin.auto.value:
        return "auto"
    if origin == PlanPositionRouteOrigin.legacy.value:
        return "legacy"
    # Default for old rows that still have route_id but no explicit origin.
    return "legacy"


def _payload_for_dynamic_build(position: PlanPosition) -> dict:
    """Build a mutable payload copy with color fallback from source_name."""
    payload = dict(position.source_payload or {})
    if not str(payload.get("color") or "").strip():
        source_text = payload.get("source_name")
        resolved = resolve_payload_color(None, str(source_text) if source_text else None)
        if resolved:
            payload["color"] = resolved
    if position.product_id and not payload.get("product_id"):
        payload["product_id"] = position.product_id
    return payload


async def _resolve_route_id_for_dynamic_name(
    db: AsyncSession,
    *,
    built_name: str,
    built_signature: str = "",
    stored_route_id: int | None,
    route_cache: dict | None = None,
) -> int | None:
    """`route_id` позиции по пересобранному маршруту; `None` — не нашли.

    Порядок: сохранённое назначение (если имя совпало) → поиск по коду из
    сигнатуры → поиск по имени → сохранённое назначение как последний выход.
    Имя пересборки берётся из шаблона профиля (`{output_kind} - {operations}`),
    и на части позиций оно не совпадает с сохранённым. Раньше это обнуляло
    назначение: позиция отдавала `route_not_found`, а take-to-work отказывал
    с HTTP 200 «No route found for this position» — при живом, назначенном
    маршруте.

    Поиск по коду (#230, ADR-0051) обязателен, а не оптимизация: имя —
    подпись, и два разных маршрута законно носят одно имя (ADR-0045). Без
    кода резолв выбирал бы «самый свежий» из одноимённых и мог указать
    позиции на маршрут чужого состава. По имени ищем только строки без кода
    (маршруты, созданные импортом до #230) — у маршрута с кодом своя
    идентичность, и подменять её догадкой по имени нельзя.

    Возвращается только id, а `route_name` вызывающий берёт из пересборки
    намеренно: страница плана обязана показывать то же имя, что и предпросмотр
    импорта (контракт закреплён `test_resolve_position_route_rebuilds_dynamic_name_over_wrong_route_id`).
    Поэтому в fallback-ветке id и имя указывают на разные строки — это цена
    совпадения с предпросмотром, а не дефект резолва.

    Сигнатура сверяется в обоих путях, как требует ADR-0051 п.4: маршрут,
    найденный по коду, мог быть переписан руками. Код — производная
    сигнатуры, но `refresh_route_signature` код не обновляет, поэтому
    переписанный маршрут продолжает находиться по своему прежнему
    `auto-`-коду. Расхождение — не «не нашли», а конфликт: подставлять такой
    маршрут нельзя (ADR-0045), поэтому поднимается `RouteSignatureConflict`,
    а вызыващий отдаёт `route_signature_conflict` строке позиции.

    Архивированный маршрут (`is_active=False`) назначением не считается: он
    прошёл бы резолв с `error=None`, выглядел бы назначенным и падал бы позже,
    в take-to-work («Route is not active», production_planning.py).
    """
    if stored_route_id is not None:
        route = await _cached_route(db, stored_route_id, route_cache)
        if route is not None and route.name == built_name and route.is_active:
            return route.id
    built_code = auto_route_code(built_signature)
    if built_code is not None:
        matched = await find_route_by_code(db, built_code, only_active=True)
        if matched is not None:
            # Код — производная сигнатуры, но пересчёт сигнатуры код не
            # обновляет (`refresh_route_signature`), поэтому маршрут,
            # переписанный руками, сохраняет старый `auto-`-код. Сверка
            # обязательна и здесь, как в импорте (ADR-0051 п.4): иначе
            # позиция получила бы маршрут чужого состава с error=None.
            if await route_signature_conflicts(db, matched, built_signature):
                raise RouteSignatureConflict(matched.id)
            return matched.id
    # Fallback по имени — только среди строк без кода (ADR-0051 п. 6), и
    # порядок тот же, что у сида и импорта: самый старый.
    legacy = await find_route_by_name(
        db, built_name, legacy_name_only=True, only_active=True
    )
    if legacy is not None:
        return legacy.id
    if stored_route_id is not None:
        stored = await _cached_route(db, stored_route_id, route_cache)
        if stored is not None and stored.is_active:
            return stored.id
    return None


async def _cached_route(
    db: AsyncSession, route_id: int, route_cache: dict | None
) -> ProductionRoute | None:
    """Fetch ProductionRoute by id, reusing the batch-level cache when provided."""
    if route_cache is not None and route_id in route_cache:
        return route_cache[route_id]
    route = await db.get(ProductionRoute, route_id)
    if route_cache is not None:
        route_cache[route_id] = route
    return route


def make_position_route_cache_key(position: PlanPosition) -> tuple:
    """Generate a cache key for route resolution based on position fields that affect it."""
    payload_key = None
    if position.source_payload:
        def make_hashable(val):
            if isinstance(val, dict):
                return tuple((k, make_hashable(v)) for k, v in sorted(val.items()))
            elif isinstance(val, list):
                return tuple(make_hashable(v) for v in val)
            return val
        payload_key = make_hashable(position.source_payload)

    return (
        position.route_id,
        position.route_origin,
        position.route_match_quality,
        position.route_match_reason,
        position.route_profile_id,
        position.product_id,
        position.import_batch_id,
        position.source_sku,
        payload_key,
    )


async def resolve_position_route(
    db: AsyncSession,
    position: PlanPosition,
    *,
    route_cache: dict | None = None,
) -> ResolvedRouteInfo:
    """Resolve route strictly from manual override + canonical position fields."""
    route_id = position.route_id
    origin = _normalize_origin(position.route_origin)
    quality = _normalize_quality(position.route_match_quality)
    reason = _normalize_reason(position.route_match_reason)
    assigned_at = position.route_assigned_at
    manual_confirmed_at = position.route_manual_confirmed_at

    # Manual override: trust stored route_id as-is.
    if (
        route_id is not None
        and origin == PlanPositionRouteOrigin.manual_confirmed.value
    ):
        route = await _cached_route(db, route_id, route_cache)
        source = _compat_source_from_origin(origin, route_id)
        if route is None:
            return ResolvedRouteInfo(
                route_id=None,
                route_name=None,
                source=source,
                route_origin=origin,
                route_match_quality=quality,
                route_match_reason=reason,
                route_assigned_at=assigned_at,
                route_manual_confirmed_at=manual_confirmed_at,
                error="manual_route_not_found",
            )
        return ResolvedRouteInfo(
            route_id=route.id,
            route_name=route.name,
            source=source,
            route_origin=origin,
            route_match_quality=quality,
            route_match_reason=reason,
            route_assigned_at=assigned_at,
            route_manual_confirmed_at=manual_confirmed_at,
            error=None,
        )

    # Dynamic profile: rebuild route name from payload (same logic as import preview).
    if position.route_profile_id is not None:
        profile = await db.get(RouteRuleProfile, position.route_profile_id)
        if profile is not None and profile.route_sections:
            try:
                payload = _payload_for_dynamic_build(position)
                built_route = await build_route_from_profile(db, profile, payload, position)

                if not built_route.error and built_route.name:
                    try:
                        resolved_route_id = await _resolve_route_id_for_dynamic_name(
                            db,
                            built_name=built_route.name,
                            built_signature=built_route.signature,
                            stored_route_id=route_id,
                            route_cache=route_cache,
                        )
                    except RouteSignatureConflict:
                        # Маршрут с этим кодом переписан руками: подставлять
                        # его нельзя (ADR-0045), и уводить позицию в
                        # сохранённое назначение тоже нельзя — конфликт
                        # виден пользователю, а не гасится в fallback.
                        return ResolvedRouteInfo(
                            route_id=None,
                            route_name=built_route.name,
                            source="dynamic_build",
                            route_origin=origin or PlanPositionRouteOrigin.auto.value,
                            route_match_quality=quality or PlanPositionRouteMatchQuality.exact.value,
                            route_match_reason=reason or PlanPositionRouteMatchReason.selection_rules.value,
                            route_assigned_at=assigned_at,
                            route_manual_confirmed_at=manual_confirmed_at,
                            error="route_signature_conflict",
                        )
                    if resolved_route_id is not None:
                        return ResolvedRouteInfo(
                            route_id=resolved_route_id,
                            # Имя — из пересборки, не у найденного маршрута:
                            # страница плана обязана совпадать с предпросмотром
                            # импорта (см. docstring резолва).
                            route_name=built_route.name,
                            source="dynamic_build",
                            route_origin=origin or PlanPositionRouteOrigin.auto.value,
                            route_match_quality=quality or PlanPositionRouteMatchQuality.exact.value,
                            route_match_reason=reason or PlanPositionRouteMatchReason.selection_rules.value,
                            route_assigned_at=assigned_at,
                            route_manual_confirmed_at=manual_confirmed_at,
                            error=None,
                        )
                    # Ничего не нашли — идём в ветку сохранённого назначения
                    # ниже: там архивный маршрут отсеется, а существующий
                    # вернётся со своим именем и без ошибки.
            except Exception:
                pass  # Fall through to stored route_id or auto selection

    # Stored route_id without dynamic profile (legacy/static assignment).
    if route_id is not None:
        route = await _cached_route(db, route_id, route_cache)
        source = _compat_source_from_origin(origin, route_id)
        # Архивированный маршрут (`is_active=False`) — это отзыв назначения,
        # а не действительный маршрут. take-to-work всё равно его отвергнет
        # («Route is not active», production_planning.py), то есть позиция
        # выглядела бы назначенной и падала бы только на запуске.
        if route is None or not route.is_active:
            return ResolvedRouteInfo(
                route_id=None,
                route_name=None,
                source=source,
                route_origin=origin,
                route_match_quality=quality,
                route_match_reason=reason,
                route_assigned_at=assigned_at,
                route_manual_confirmed_at=manual_confirmed_at,
                error="route_not_found",
            )

        return ResolvedRouteInfo(
            route_id=route.id,
            route_name=route.name,
            source=source,
            route_origin=origin,
            route_match_quality=quality,
            route_match_reason=reason,
            route_assigned_at=assigned_at,
            route_manual_confirmed_at=manual_confirmed_at,
            error=None,
        )

    # No stored route_id - try to resolve from source_payload
    import_batch = await db.get(ImportBatch, position.import_batch_id) if position.import_batch_id is not None else None
    rule_profile_id = import_batch.rule_profile_id if import_batch is not None else None

    product = (
        await db.execute(
            select(Product).options(selectinload(Product.processing_flags)).where(Product.id == position.product_id)
        )
    ).scalar_one_or_none() if position.product_id is not None else None
    selection = await select_route_for_payload(db, position.source_payload, product, profile_id=rule_profile_id)
    if selection.route is None:
        return ResolvedRouteInfo(
            route_id=None,
            route_name=None,
            source="missing",
            route_origin=None,
            route_match_quality=None,
            route_match_reason=selection.route_match_reason,
            route_assigned_at=None,
            route_manual_confirmed_at=None,
            error=selection.error or "route_not_found",
            checked_rules=selection.matched_rule_ids,
            required_sections=selection.required_sections,
            excluded_sections=selection.excluded_sections,
            candidate_routes=selection.candidate_routes,
            selected_route_id=None,
            condition_diagnostics=selection.condition_diagnostics,
        )
    return ResolvedRouteInfo(
        route_id=selection.route.id,
        route_name=selection.route.name,
        source="auto",
        route_origin=PlanPositionRouteOrigin.auto.value,
        route_match_quality=selection.route_match_quality or PlanPositionRouteMatchQuality.exact.value,
        route_match_reason=PlanPositionRouteMatchReason.selection_rules.value,
        route_assigned_at=None,
        route_manual_confirmed_at=None,
        error=None,
        checked_rules=selection.matched_rule_ids,
        required_sections=selection.required_sections,
        excluded_sections=selection.excluded_sections,
        candidate_routes=selection.candidate_routes,
        selected_route_id=selection.route.id,
        condition_diagnostics=selection.condition_diagnostics,
    )
