from __future__ import annotations

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.product import Product
from app.models.techcard import Techcard, TechcardLine

# Типизированные данные из канона (ADR-0004). Сервис не импортирует plant_policies.
from app.seeds.canon.registry import build_plant_config as _build

_PAIRED_PROCESSING_VALUE: str = _build().production.processing_flags.paired

TECHCARD_SORT_FIELDS = frozenset({
    "id",
    "sku",
    "quantity",
    "quantity_total",
    "version",
    "processing_type",
    "is_active",
})


def _paired_sku_subquery():
    component = aliased(Product)
    return (
        select(func.string_agg(component.sku, " + ").within_group(component.sku))
        .select_from(
            TechcardLine.__table__.join(component, component.id == TechcardLine.component_product_id)
        )
        .where(TechcardLine.techcard_id == Techcard.id)
        .correlate(Techcard)
        .scalar_subquery()
    )


def _apply_techcard_filters(
    stmt,
    *,
    search: str | None = None,
    processing_type: str | None = None,
    is_active: bool | None = None,
    sku: str | None = None,
    quantity_total: int | None = None,
    product: aliased(Product) | None = None,
):
    if processing_type:
        stmt = stmt.where(Techcard.processing_type == processing_type)
    if is_active is not None:
        stmt = stmt.where(Techcard.is_active.is_(is_active))
    if quantity_total is not None:
        stmt = stmt.where(Techcard.quantity_total == quantity_total)

    if sku:
        sku_like = f"%{sku}%"
        line_exists = exists(
            select(1)
            .select_from(TechcardLine.__table__.join(Product, Product.id == TechcardLine.component_product_id))
            .where(TechcardLine.techcard_id == Techcard.id)
            .where(Product.sku.ilike(sku_like))
        )
        if product is not None:
            stmt = stmt.where(or_(product.sku.ilike(sku_like), line_exists))
        else:
            stmt = stmt.where(line_exists)

    if search:
        search_like = f"%{search}%"
        line_search = exists(
            select(1)
            .select_from(TechcardLine.__table__.join(Product, Product.id == TechcardLine.component_product_id))
            .where(TechcardLine.techcard_id == Techcard.id)
            .where(
                or_(
                    Product.sku.ilike(search_like),
                    Product.name.ilike(search_like),
                )
            )
        )
        if product is not None:
            stmt = stmt.where(
                or_(
                    product.sku.ilike(search_like),
                    product.name.ilike(search_like),
                    line_search,
                )
            )
        else:
            stmt = stmt.where(line_search)

    return stmt


def _resolve_techcard_order_columns(sort_by: str, product: aliased(Product) | None):
    if sort_by == "sku":
        if product is not None:
            return case(
                (Techcard.product_id.is_not(None), product.sku),
                else_=_paired_sku_subquery(),
            )
        return _paired_sku_subquery()
    if sort_by in {"quantity", "quantity_total"}:
        return Techcard.quantity_total
    if sort_by == "version":
        return Techcard.version
    if sort_by == "processing_type":
        return Techcard.processing_type
    if sort_by == "is_active":
        return Techcard.is_active
    return Techcard.id


async def list_techcards_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort_by: str = "id",
    sort_order: str = "desc",
    processing_type: str | None = None,
    is_active: bool | None = None,
    sku: str | None = None,
    quantity_total: int | None = None,
) -> tuple[list[Techcard], int]:
    resolved_sort_by = sort_by if sort_by in TECHCARD_SORT_FIELDS else "id"
    product = aliased(Product)

    stmt = select(Techcard).outerjoin(product, Techcard.product_id == product.id)
    stmt = _apply_techcard_filters(
        stmt,
        search=search,
        processing_type=processing_type,
        is_active=is_active,
        sku=sku,
        quantity_total=quantity_total,
        product=product,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    order_column = _resolve_techcard_order_columns(resolved_sort_by, product)
    if sort_order == "desc":
        stmt = stmt.order_by(order_column.desc().nulls_last(), Techcard.id.desc())
    else:
        stmt = stmt.order_by(order_column.asc().nulls_last(), Techcard.id.asc())

    stmt = stmt.limit(limit).offset(offset)
    techcards = list((await db.execute(stmt)).scalars().unique().all())
    return techcards, total


async def enrich_techcard_list_items(
    db: AsyncSession,
    techcards: list[Techcard],
) -> list[dict]:
    if not techcards:
        return []

    product_ids = {tc.product_id for tc in techcards if tc.product_id is not None}
    paired_ids = [tc.id for tc in techcards if tc.processing_type == _PAIRED_PROCESSING_VALUE]

    product_skus: dict[int, str] = {}
    if product_ids:
        rows = (
            await db.execute(select(Product.id, Product.sku).where(Product.id.in_(product_ids)))
        ).all()
        product_skus = {row.id: row.sku for row in rows}

    lines_by_tc: dict[int, list[dict]] = {}
    if paired_ids:
        component = aliased(Product)
        lines = (
            await db.execute(
                select(TechcardLine, component.sku)
                .outerjoin(component, component.id == TechcardLine.component_product_id)
                .where(TechcardLine.techcard_id.in_(paired_ids))
                .order_by(TechcardLine.techcard_id, TechcardLine.id)
            )
        ).all()
        for line, component_sku in lines:
            lines_by_tc.setdefault(line.techcard_id, []).append({
                "id": line.id,
                "component_product_id": line.component_product_id,
                "component_product_sku": component_sku,
                "quantity": line.quantity,
                "unit": line.unit,
            })

    result: list[dict] = []
    for item in techcards:
        data = {
            "id": item.id,
            "product_id": item.product_id,
            "version": item.version,
            "processing_type": item.processing_type,
            "is_active": item.is_active,
            "quantity_total": item.quantity_total,
            "quantity_a_per_item": item.quantity_a_per_item,
            "quantity_b_per_item": item.quantity_b_per_item,
            "hangers_a": item.hangers_a,
            "hangers_b": item.hangers_b,
            "hangers_total": item.hangers_total,
            "product_sku": product_skus.get(item.product_id) if item.product_id else None,
            "techcard_lines": lines_by_tc.get(item.id, []) if item.processing_type == _PAIRED_PROCESSING_VALUE else [],
        }
        result.append(data)
    return result