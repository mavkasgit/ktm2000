from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.route_matcher import resolve_position_route


VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "product_not_found": "Продукт не найден",
    "quantity_must_be_positive": "Количество должно быть положительным",
    "product_inactive": "Продукт неактивен",
    "active_techcard_not_found": "Не найдена активная техкарта для продукта",
    "active_techcard_has_no_lines": "Техкарта не содержит операций",
    "route_not_found": "Не найден маршрут для позиции",
    "no_route_candidate": "Не найден маршрут, удовлетворяющий правилам выбора",
    "route_rule_conflict": "Правила выбора маршрута конфликтуют",
    "route_contains_excluded_step": "Маршрут содержит запрещенный правилами участок",
    "selection_rules": "Маршрут выбран правилами",
    "route_signature_incomplete": "Сигнатура маршрута позиции неполная",
    "active_route_has_no_steps": "Маршрут не содержит этапов",
    "route_sequence_invalid": "Неверная последовательность этапов в маршруте",
    "route_contains_inactive_section": "Маршрут содержит неактивный участок",
    "duplicate_sku_due_date": "Дубликат строки Excel: такая же строка уже есть в плане.",
    "route_not_matching_import_signature": "Маршрут не совпадает с ожидаемым",
    "route_missing_required_step": "В маршруте отсутствует обязательный этап",
    "route_missing_pack_additional_operation": "В маршруте нет дополнительной операции упаковки",
    "route_primary_operation_mismatch": "Основная операция маршрута не совпадает с импортированной. Проверьте соответствие техкарты и маршрута.",
}


def format_validation_error(error_code: str) -> str:
    """Преобразует технический код ошибки в понятное сообщение."""
    if ":" in error_code:
        base_code, detail = error_code.split(":", 1)
        base_code = base_code.strip()
        detail = detail.strip()
        message = VALIDATION_ERROR_MESSAGES.get(base_code)
        if message:
            return f"{message} ({detail})"
        return detail
    return VALIDATION_ERROR_MESSAGES.get(error_code, error_code)


def _normalize_sku(value: str) -> str:
    normalized = (value or "").strip().lower()
    dash_variants = "\u2010\u2011\u2012\u2013\u2014\u2212\u2043\uFE58\uFE63\uFF0D"
    for ch in dash_variants:
        normalized = normalized.replace(ch, "-")
    return normalized.replace(" ", "").replace("\u00A0", "")


def _paired_component_skus(position: PlanPosition) -> list[str]:
    payload = position.source_payload or {}
    components = payload.get("components") or []
    if not isinstance(components, list):
        return []
    return [str(item.get("sku") or "").strip() for item in components if str(item.get("sku") or "").strip()]


async def _find_paired_techcard(db: AsyncSession, component_skus: list[str]) -> Techcard | None:
    if not component_skus:
        return None
    normalized_keys = {_normalize_sku(sku) for sku in component_skus if _normalize_sku(sku)}
    if not normalized_keys:
        return None

    techcards = (
        await db.execute(
            select(Techcard).where(
                Techcard.is_active.is_(True),
                Techcard.processing_type == "paired_processing",
            )
        )
    ).scalars().all()

    for techcard in techcards:
        rows = (
            await db.execute(
                select(TechcardLine, Product)
                .join(Product, Product.id == TechcardLine.component_product_id)
                .where(TechcardLine.techcard_id == techcard.id)
            )
        ).all()
        line_skus = {_normalize_sku(product.sku) for _, product in rows if product and product.sku}
        if normalized_keys.issubset(line_skus):
            return techcard
    return None


async def validate_plan_position(db: AsyncSession, position: PlanPosition) -> list[str]:
    errors: list[str] = []
    is_paired_profile = bool((position.source_payload or {}).get("paired_profile"))
    if position.product_id is None and not is_paired_profile:
        errors.append("product_not_found")
        return errors
    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    if position.product_id is not None:
        product = await db.get(Product, position.product_id)
        if product is None or not product.is_active:
            errors.append("product_inactive")

        techcard = await db.scalar(
            select(Techcard).where(Techcard.product_id == position.product_id, Techcard.is_active.is_(True))
        )
        if techcard is None:
            errors.append("active_techcard_not_found")
        else:
            line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
            if line is None:
                errors.append("active_techcard_has_no_lines")
    else:
        techcard = await _find_paired_techcard(db, _paired_component_skus(position))
        if techcard is None:
            errors.append("active_techcard_not_found")
        else:
            line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
            if line is None:
                errors.append("active_techcard_has_no_lines")

    product = await db.get(Product, position.product_id) if position.product_id else None
    route_info = await resolve_position_route(db, position)
    if route_info.route_id is None:
        errors.append(route_info.error or "route_not_found")
    else:
        steps = (
            await db.execute(select(RouteStep).where(RouteStep.route_id == route_info.route_id).order_by(RouteStep.sequence))
        ).scalars().all()
        if not steps:
            errors.append("active_route_has_no_steps")
        previous = 0
        for step in steps:
            if step.sequence <= previous:
                errors.append("route_sequence_invalid")
                break
            previous = step.sequence
            section = await db.get(Section, step.section_id)
            if section is None or not section.is_active:
                errors.append("route_contains_inactive_section")
                break

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
            errors.append("duplicate_sku_due_date")

    from app.services.route_validation import validate_route_match

    route_errors = await validate_route_match(db, position)
    errors.extend(route_errors)

    return errors
