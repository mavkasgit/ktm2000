from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.techcard import TechcardPair, TechcardPairLine
from app.models.product import Product


@dataclass(slots=True)
class TechcardPairResolutionResult:
    resolved: bool
    variant_id: int | None
    variant_name: str | None
    priority: int | None
    reason: str | None
    inputs: list[dict]


async def resolve_techcard_pair(
    db: AsyncSession,
    *,
    techcard_id: int,
    available_by_sku: dict[str, Decimal],
    target_quantity: Decimal,
) -> TechcardPairResolutionResult:
    pairs = (
        await db.execute(
            select(TechcardPair)
            .where(TechcardPair.techcard_id == techcard_id, TechcardPair.is_active.is_(True))
            .order_by(TechcardPair.priority.asc(), TechcardPair.id.asc())
        )
    ).scalars().all()
    if not pairs:
        return TechcardPairResolutionResult(False, None, None, None, "no_active_pairs", [])

    for variant in pairs:
        lines = (
            await db.execute(
                select(TechcardPairLine, Product)
                .join(Product, Product.id == TechcardPairLine.component_product_id)
                .where(TechcardPairLine.techcard_pair_id == variant.id)
                .order_by(TechcardPairLine.id.asc())
            )
        ).all()
        if not lines:
            continue

        fits = True
        resolved_inputs: list[dict] = []
        for line, product in lines:
            sku_key = product.sku.lower()
            required = target_quantity * Decimal(str(line.quantity))
            available = available_by_sku.get(sku_key, Decimal("0"))
            resolved_inputs.append(
                {
                    "product_id": product.id,
                    "sku": product.sku,
                    "required_quantity": str(required),
                    "available_quantity": str(available),
                    "unit": line.unit,
                }
            )
            if available < required:
                fits = False

        if fits:
            return TechcardPairResolutionResult(
                True,
                variant.id,
                variant.name,
                int(variant.priority),
                None,
                resolved_inputs,
            )

    return TechcardPairResolutionResult(False, None, None, None, "insufficient_or_missing_inputs", [])
