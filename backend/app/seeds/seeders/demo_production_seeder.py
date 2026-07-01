from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductType
from app.models.spg import StorageProductionGroup
from app.models.spg_remainder import SpgRemainder
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile
from app.models.section import Section
from app.models.defect import Defect, DefectItem, DefectStatus, DefectDecision, DefectDecisionType
from app.models.user import User
from app.services.shopfloor.common import build_completed_stages_json


PREP_STOCK_CODE = "PREP_STOCK"
WIP_STOCK_CODE = "WIP"


async def seed_demo_production(db: AsyncSession) -> dict:
    """Seed demo remainders, route stages, and defects for manual workflows.

    Returns stats of seeded records.
    """
    stats = {"products": 0, "remainders": 0, "defects": 0}

    # 1. Ensure demo products exist
    demo_skus = ["ЮП-100-2700-BL", "АТ-200-2700-AN"]
    products_by_sku = {}
    for sku in demo_skus:
        prod = await db.scalar(select(Product).where(Product.sku == sku))
        if not prod:
            prod = Product(
                sku=sku,
                name=f"Профиль универсальный {sku.split('-')[-1]}" if "BL" in sku else f"Профиль анодированный {sku.split('-')[-1]}",
                type=ProductType.component,
                unit="pcs",
                is_active=True,
                profile_type="universal" if "ЮП" in sku else "tube",
                alloy="6063",
                color="Blue" if "BL" in sku else "Silver",
                length_mm=2700.0,
                is_catalog_item=True,
            )
            db.add(prod)
            await db.flush()
            stats["products"] += 1
        products_by_sku[sku] = prod

    # 2. Resolve SPGs (in priority order):
    #    - prep_stock: целевой склад для остатков прерванных задач подготовки
    #    - wip_stock: целевой склад для остатков прерванных задач после анодирования
    #    - fallback_spg: первый активный SPG (используется, если ни один не засеян)
    prep_stock = await db.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == PREP_STOCK_CODE)
    )
    wip_stock = await db.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == WIP_STOCK_CODE)
    )
    fallback_spg = await db.scalar(
        select(StorageProductionGroup)
        .where(StorageProductionGroup.is_active == True)
        .order_by(StorageProductionGroup.sort_order)
        .limit(1)
    )
    spg = prep_stock or wip_stock or fallback_spg
    if not spg:
        return stats  # No SPG to seed remainders onto

    # 3. Find default route stages
    route = await db.scalar(
        select(ProductionRoute)
        .where(ProductionRoute.code == "dynamic_packaging_map_rp")
        .limit(1)
    )
    if not route:
        # Get first active route
        route = await db.scalar(
            select(ProductionRoute)
            .where(ProductionRoute.is_active == True)
            .limit(1)
        )

    if not route:
        return stats  # No route to map stages from

    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route.id)
            .order_by(RouteStage.sequence)
            .options(selectinload(RouteStage.operations))
        )
    ).scalars().all()

    if not stages:
        return stats

    # 4. Get a user
    user = await db.scalar(select(User).limit(1))
    actor_id = user.id if user else 1
    actor_name = user.full_name or user.username if user else "system"

    # 5. Create remainders
    # Remainder 1: ЮП-100-2700-BL, completed stages up to stage 2 (e.g. WH, DRILL)
    # Не показываем незначимые (WH-выдача сырья) — оставляем только реальные операции.
    rem1_sku = "ЮП-100-2700-BL"
    rem1_prod = products_by_sku[rem1_sku]
    completed_stages1 = await build_completed_stages_json(db, stages[:2])

    rem1 = await db.scalar(
        select(SpgRemainder)
        .where(
            SpgRemainder.product_id == rem1_prod.id,
            SpgRemainder.spg_id == spg.id,
            SpgRemainder.source == "manual",
        )
        .limit(1)
    )
    if not rem1:
        rem1 = SpgRemainder(
            product_id=rem1_prod.id,
            spg_id=spg.id,
            route_stage_id=None,
            section_plan_line_id=None,
            origin_task_id=None,
            remainder_quantity=Decimal("150.000"),
            original_issued=Decimal("150.000"),
            completed_stages_json=completed_stages1,
            source="manual",
            created_by=actor_id,
            created_by_user_name=actor_name,
        )
        db.add(rem1)
        await db.flush()
        stats["remainders"] += 1

    # Remainder 2: АТ-200-2700-AN, completed stages up to stage 4 (после анодирования, до упаковки).
    # Тоже фильтруем незначимые операции (WH-выдача, WIP-передача).
    rem2_sku = "АТ-200-2700-AN"
    rem2_prod = products_by_sku[rem2_sku]
    completed_stages2 = await build_completed_stages_json(db, stages[:4])

    rem2 = await db.scalar(
        select(SpgRemainder)
        .where(
            SpgRemainder.product_id == rem2_prod.id,
            SpgRemainder.spg_id == spg.id,
            SpgRemainder.source == "manual",
        )
        .limit(1)
    )
    if not rem2:
        rem2 = SpgRemainder(
            product_id=rem2_prod.id,
            spg_id=spg.id,
            route_stage_id=None,
            section_plan_line_id=None,
            origin_task_id=None,
            remainder_quantity=Decimal("80.000"),
            original_issued=Decimal("80.000"),
            completed_stages_json=completed_stages2,
            source="manual",
            created_by=actor_id,
            created_by_user_name=actor_name,
        )
        db.add(rem2)
        await db.flush()
        stats["remainders"] += 1

    # 6. Create defects (только если остатки попали в PREP_STOCK — иначе привязка неуместна)
    if prep_stock is None:
        await db.flush()
        return stats

    # Defect 1: Open defect for ЮП-100-2700-BL на первой значимой стадии подготовки.
    significant_stages = await build_completed_stages_json(db, stages)
    first_sig_seq = significant_stages[0]["sequence"] if significant_stages else stages[0].sequence
    drill_stage = next(
        (s for s in stages if s.sequence == first_sig_seq),
        stages[1] if len(stages) > 1 else stages[0],
    )

    existing_def1 = await db.scalar(
        select(Defect)
        .where(Defect.product_id == rem1_prod.id, Defect.route_stage_id == drill_stage.id, Defect.spg_remainder_id == rem1.id)
        .limit(1)
    )
    if not existing_def1:
        def1 = Defect(
            product_id=rem1_prod.id,
            section_id=drill_stage.section_id,
            task_id=None,
            route_stage_id=drill_stage.id,
            spg_remainder_id=rem1.id,
            status=DefectStatus.decision_required,
            comment="Царапины после сверловки (демо)",
            created_by=actor_id,
        )
        db.add(def1)
        await db.flush()

        item1 = DefectItem(
            defect_id=def1.id,
            quantity=Decimal("5.000"),
            defect_type_code_snapshot="scratches",
            defect_type_name_snapshot="Царапины",
            description="Глубокие царапины на лицевой поверхности",
            created_by=actor_id,
        )
        db.add(item1)
        stats["defects"] += 1

    # Defect 2: Open defect for АТ-200-2700-AN на стадии анодирования
    anod_stage = stages[3] if len(stages) > 3 else stages[0]
    existing_def2 = await db.scalar(
        select(Defect)
        .where(Defect.product_id == rem2_prod.id, Defect.route_stage_id == anod_stage.id, Defect.spg_remainder_id == rem2.id)
        .limit(1)
    )
    if not existing_def2:
        def2 = Defect(
            product_id=rem2_prod.id,
            section_id=anod_stage.section_id,
            task_id=None,
            route_stage_id=anod_stage.id,
            spg_remainder_id=rem2.id,
            status=DefectStatus.decision_required,
            comment="Непрокрас краев (демо)",
            created_by=actor_id,
        )
        db.add(def2)
        await db.flush()

        item2 = DefectItem(
            defect_id=def2.id,
            quantity=Decimal("3.000"),
            defect_type_code_snapshot="paint_defect",
            defect_type_name_snapshot="Дефект покраски",
            description="Непрокрас анодного слоя по краям профиля",
            created_by=actor_id,
        )
        db.add(item2)
        stats["defects"] += 1

    await db.flush()
    return stats
