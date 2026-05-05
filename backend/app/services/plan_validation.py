from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.route_matcher import find_route, resolve_position_route


VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "product_not_found": "Продукт не найден",
    "quantity_must_be_positive": "Количество должно быть положительным",
    "product_inactive": "Продукт неактивен",
    "active_techcard_not_found": "Не найдена активная техкарта для продукта",
    "active_techcard_has_no_lines": "Техкарта не содержит операций",
    "active_route_not_found": "Не найден активный маршрут для продукта",
    "active_route_has_no_steps": "Маршрут не содержит этапов",
    "route_sequence_invalid": "Неверная последовательность этапов в маршруте",
    "route_contains_inactive_section": "Маршрут содержит неактивный участок",
    "duplicate_sku_due_date": "Дубликат: позиция с таким артикулом и сроком уже есть в плане. Объедините количество или измените срок.",
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


async def validate_plan_position(db: AsyncSession, position: PlanPosition) -> list[str]:
    errors: list[str] = []
    if position.product_id is None:
        errors.append("product_not_found")
        return errors
    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    product = await db.get(Product, position.product_id)
    if product is None or not product.is_active:
        errors.append("product_inactive")

    techcard = await db.scalar(select(Techcard).where(Techcard.product_id == position.product_id, Techcard.is_active.is_(True)))
    if techcard is None:
        errors.append("active_techcard_not_found")
    else:
        line = await db.scalar(select(TechcardLine.id).where(TechcardLine.techcard_id == techcard.id).limit(1))
        if line is None:
            errors.append("active_techcard_has_no_lines")

    product = await db.get(Product, position.product_id) if position.product_id else None
    route_info = await resolve_position_route(db, position.route_id, product)
    if route_info.route_id is None:
        errors.append("active_route_not_found")
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

    duplicate_stmt = (
        select(PlanPosition)
        .where(
            PlanPosition.production_plan_id == position.production_plan_id,
            PlanPosition.source_sku == position.source_sku,
            PlanPosition.due_date == position.due_date,
            PlanPosition.status != PlanPositionStatus.cancelled,
        )
    )
    if position.id is not None:
        duplicate_stmt = duplicate_stmt.where(PlanPosition.id != position.id)
    duplicate = await db.scalar(duplicate_stmt)
    if duplicate is not None:
        errors.append("duplicate_sku_due_date")

    from app.services.route_validation import validate_route_match

    route_errors = await validate_route_match(db, position)
    errors.extend(route_errors)

    return errors
