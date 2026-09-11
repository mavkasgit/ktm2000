from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.services import product_pair_resolver
from app.services.product_pair_resolver import paired_component_skus
from app.services.route_matcher import resolve_position_route

# Типизированные данные из канона (ADR-0004). Сервис не импортирует plant_policies.
from app.seeds.canon.registry import build_plant_config as _build

_config = _build()
_ERROR_MESSAGES: dict[str, str] = _config.display.labels.error_messages


def format_validation_error(
    error_code: str, error_messages: dict[str, str] | None = None
) -> str:
    """Преобразует технический код ошибки в понятное сообщение.

    Тексты читаются из канона заводской конфигурации (ADR-0004);
    при отсутствии кода в данных — fallback на сам код.
    """
    messages = error_messages if error_messages is not None else _ERROR_MESSAGES
    if ":" in error_code:
        base_code, detail = error_code.split(":", 1)
        base_code = base_code.strip()
        detail = detail.strip()
        message = messages.get(base_code)
        if message:
            return f"{message} ({detail})"
        return detail
    return messages.get(error_code, error_code)


async def validate_plan_position(
    db: AsyncSession,
    position: PlanPosition,
    *,
    route_resolve_cache: dict | None = None,
    select_route_cache: dict | None = None,
    route_stages_cache: dict | None = None,
    sections_cache: dict | None = None,
    existing_fingerprints: set[str] | None = None,
    existing_row_hashes: set[str] | None = None,
    product_cache: dict | None = None,
    route_cache: dict | None = None,
) -> list[str]:
    errors: list[str] = []
    payload = position.source_payload or {}
    is_paired_profile = bool(payload.get("paired_profile"))
    if position.product_id is None and not is_paired_profile:
        errors.append("product_not_found")
        return errors
    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    # Gate «активная техкарта» упразднён (ADR-0023, #148): валидация
    # одиночной позиции = SKU найден, активен, маршрут разрешён и валиден.
    if position.product_id is None:
        product = None
    elif product_cache is not None and position.product_id in product_cache:
        product = product_cache[position.product_id]
    else:
        product = await db.get(Product, position.product_id)
        if product_cache is not None:
            product_cache[position.product_id] = product
    if position.product_id is not None:
        if product is None or not product.is_active:
            errors.append("product_inactive")

    # Парная позиция резолвится из product_pairs (#148). Позиция с непустым
    # снапшотом (product_pair.resolved) — норматив позиции: пара и нормы
    # не ревалидируются (#142).
    from app.services.plan_position_hanger import (
        payload_quantity_per_hanger,
        position_length_mm,
        resolve_position_hanger,
    )

    if is_paired_profile:
        if not product_pair_resolver.has_pair_snapshot(position):
            resolved_pair = await product_pair_resolver.resolve_pair_by_component_skus(
                db, paired_component_skus(position)
            )
            if resolved_pair is None:
                errors.append("product_pair_not_found")
            else:
                n_value = await product_pair_resolver.resolve_pair_n(
                    db, resolved_pair, length_mm=position_length_mm(position),
                    manual_override=payload_quantity_per_hanger(position),
                )
                if n_value.calc_error:
                    errors.append("hanger_calc_zero")
    else:
        # Авторасчёт «количество на подвес» (#66): невозможный расчёт
        # (total <= 0 или несовместимые габариты) блокирует позицию от
        # утверждения/релиза. Приоритет: ручной override из payload > авто;
        # при ручном override ошибка не выставляется.
        hanger_value = resolve_position_hanger(
            product,
            length_mm=position_length_mm(position),
            payload_quantity_per_hanger=payload_quantity_per_hanger(position),
        )
        if hanger_value.calc_error:
            errors.append("hanger_calc_zero")

    if route_resolve_cache is not None:
        from app.services.route_matcher import make_position_route_cache_key
        cache_key = make_position_route_cache_key(position)
        if cache_key in route_resolve_cache:
            route_info = route_resolve_cache[cache_key]
        else:
            route_info = await resolve_position_route(db, position, route_cache=route_cache)
            route_resolve_cache[cache_key] = route_info
    else:
        route_info = await resolve_position_route(db, position, route_cache=route_cache)

    if route_info.route_id is None:
        errors.append(route_info.error or "route_not_found")
    else:
        if route_stages_cache is not None and route_info.route_id in route_stages_cache:
            steps = route_stages_cache[route_info.route_id]
        else:
            steps = (
                await db.execute(select(RouteStage).where(RouteStage.route_id == route_info.route_id).order_by(RouteStage.sequence))
            ).scalars().all()
            if route_stages_cache is not None:
                route_stages_cache[route_info.route_id] = steps

        if not steps:
            errors.append("active_route_has_no_steps")
        previous = 0
        for step in steps:
            if step.sequence <= previous:
                errors.append("route_sequence_invalid")
                break
            previous = step.sequence

            effective_section_id = step.effective_section_id
            if sections_cache is not None and effective_section_id in sections_cache:
                section = sections_cache[effective_section_id]
            else:
                section = await db.get(Section, effective_section_id)
                if sections_cache is not None and section is not None:
                    sections_cache[effective_section_id] = section

            if section is None or not section.is_active:
                errors.append("route_contains_inactive_section")
                break

    # Проверка дубликатов
    is_duplicate = False
    if existing_fingerprints is not None and position.source_fingerprint:
        if position.source_fingerprint in existing_fingerprints:
            is_duplicate = True
    elif existing_row_hashes is not None and position.source_row_hash:
        if position.source_row_hash in existing_row_hashes:
            is_duplicate = True
    else:
        duplicate_stmt = None
        if position.source_fingerprint:
            duplicate_stmt = (
                select(PlanPosition)
                .where(
                    PlanPosition.production_plan_id == position.production_plan_id,
                    PlanPosition.source_fingerprint == position.source_fingerprint,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )
        elif position.source_row_hash:
            duplicate_stmt = (
                select(PlanPosition)
                .where(
                    PlanPosition.production_plan_id == position.production_plan_id,
                    PlanPosition.source_row_hash == position.source_row_hash,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )

        if duplicate_stmt is not None:
            if position.id is not None:
                duplicate_stmt = duplicate_stmt.where(PlanPosition.id != position.id)
            duplicate = await db.scalar(duplicate_stmt)
            if duplicate is not None:
                is_duplicate = True

    if is_duplicate:
        errors.append("duplicate_sku_due_date")

    from app.services.route_validation import validate_route_match

    route_errors = await validate_route_match(
        db, position,
        route_resolve_cache=route_resolve_cache,
        select_route_cache=select_route_cache,
        route_stages_cache=route_stages_cache,
        sections_cache=sections_cache,
        route_cache=route_cache,
    )
    errors.extend(route_errors)

    return errors
