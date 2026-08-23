from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductType
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile
from app.models.section import Section
from app.models.defect import Defect, DefectItem, DefectStatus, DefectDecision, DefectDecisionType
from app.models.user import User
from app.services.route_storage_classifier import (
    STAGE_KIND_PRODUCTION,
    is_production_stage,
    is_transit_stage,
)
from app.services.shopfloor.common import build_completed_stages_json


PREP_STOCK_SECTION_CODE = "PREP_STOCK"
WIP_STOCK_SECTION_CODE = "WIP_STOCK"


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
    #    - prep_stock: SPG, содержащий секцию PREP_STOCK (целевой склад для остатков подготовки)
    #    - wip_stock: ГХП полуфабриката после анодирования
    #    - fallback_spg: первый активный SPG (используется, если ни один не засеян)
    prep_stock = await db.scalar(
        select(StorageProductionGroup)
        .join(SpgSection, SpgSection.spg_id == StorageProductionGroup.id)
        .join(Section, SpgSection.section_id == Section.id)
        .where(Section.code == PREP_STOCK_SECTION_CODE)
    )
    wip_stock = await db.scalar(
        select(StorageProductionGroup)
        .join(SpgSection, SpgSection.spg_id == StorageProductionGroup.id)
        .join(Section, SpgSection.section_id == Section.id)
        .where(Section.code == WIP_STOCK_SECTION_CODE)
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
            .options(
                selectinload(RouteStage.operations),
                selectinload(RouteStage.section),
                selectinload(RouteStage.storage_section),
            )
        )
    ).scalars().all()

    if not stages:
        return stats

    # Build section_code -> stage map.  With the new model storage sections
    # appear as transit stages; we still resolve them by section code so the
    # seeder is robust to either route shape.
    sections_in_route = {s.section_id for s in stages if s.section_id is not None}
    sections_in_route |= {s.storage_section_id for s in stages if s.storage_section_id is not None}
    sections_rows = (await db.execute(
        select(Section).where(Section.id.in_(sections_in_route))
    )).scalars().all() if sections_in_route else []
    sections_by_id = {s.id: s for s in sections_rows}

    def _code_of_stage(stage: RouteStage) -> str | None:
        if stage.storage_section_id is not None:
            return sections_by_id.get(stage.storage_section_id).code if stage.storage_section_id in sections_by_id else None
        if stage.section_id is not None:
            return sections_by_id.get(stage.section_id).code if stage.section_id in sections_by_id else None
        return None

    # Production stages only (transit stages are not work, just storage hops)
    production_stages = [s for s in stages if is_production_stage(s)]

    def _find_production_by_code(code: str) -> RouteStage | None:
        for s in production_stages:
            if s.section and s.section.code == code:
                return s
        return None

    # 4. Get a user
    user = await db.scalar(select(User).limit(1))
    actor_id = user.id if user else 1
    actor_name = user.full_name or user.username if user else "system"

    # 5. Create remainders
    # Remainder 1: ЮП-100-2700-BL, completed stages through DRILL
    # (after сверловка, before пресс).  Transit stages (WH) are filtered out
    # by build_completed_stages_json.
    rem1_sku = "ЮП-100-2700-BL"
    rem1_prod = products_by_sku[rem1_sku]
    drill_stage = _find_production_by_code("DRILLING")
    press_stage = _find_production_by_code("PRESSING")
    if drill_stage is not None and press_stage is not None:
        # Take everything from the start up to (but not including) PRESS
        drill_seq = drill_stage.sequence
        stages_through_drill = [s for s in stages if s.sequence <= drill_seq]
    else:
        # Fallback: first two production stages
        stages_through_drill = production_stages[:2]
    completed_stages1 = await build_completed_stages_json(db, stages_through_drill)

    # SpgRemainder creation removed — table no longer exists.
    # Use StockCommandService.MANUAL_IN for demo stock creation.
    from app.stock import StockCommand, StockCommandService, Reason, QualityState
    from app.stock.models import StockTransaction
    stock_service = StockCommandService()

    # Find target section for remainder
    target_sec = None
    if prep_stock:
        target_sec = await db.scalar(
            select(Section)
            .join(SpgSection, SpgSection.section_id == Section.id)
            .where(SpgSection.spg_id == prep_stock.id)
            .limit(1)
        )
    if not target_sec and spg:
        target_sec = await db.scalar(
            select(Section)
            .join(SpgSection, SpgSection.section_id == Section.id)
            .where(SpgSection.spg_id == spg.id)
            .limit(1)
        )
    if not target_sec:
        target_sec = await db.scalar(
            select(Section).where(Section.is_active == True).limit(1)
        )

    # Журнал действий (#116): один Action('seed_demo') на весь сид,
    # компенсатора нет (решения 2 и 7 спеки). Создаётся лениво — только
    # если сид реально порождает новые проводки.
    from app.services.action_journal_service import action_journal_service

    seed_action = None
    if target_sec is not None:
        existing_tx1 = await db.scalar(
            select(StockTransaction)
            .where(
                StockTransaction.product_id == rem1_prod.id,
                StockTransaction.to_location_id == target_sec.id,
                StockTransaction.reason == Reason.MANUAL_IN
            )
            .limit(1)
        )
        if existing_tx1:
            tx1 = existing_tx1
        else:
            if seed_action is None:
                seed_action = await action_journal_service.log(
                    db, action_type="seed_demo",
                )
            tx1 = await stock_service.record(db, StockCommand(
                product_id=rem1_prod.id,
                quantity=Decimal("150.000"),
                reason=Reason.MANUAL_IN,
                to_location_id=target_sec.id,
                quality_state=QualityState.GOOD,
                created_by=actor_id,
                comment="Demo stock for remainder 1",
                action_id=seed_action.id,
            ))
            stats["remainders"] += 1

    # Remainder 2: АТ-200-2700-AN, completed stages through SHOT
    # (after дробеструй, before анодирование).
    rem2_sku = "АТ-200-2700-AN"
    rem2_prod = products_by_sku[rem2_sku]
    shot_stage = _find_production_by_code("SHOT_BLAST")
    anod_stage = _find_production_by_code("ANODIZING")
    if shot_stage is not None and anod_stage is not None:
        shot_seq = shot_stage.sequence
        stages_through_shot = [s for s in stages if s.sequence <= shot_seq]
    else:
        # Fallback: first four production stages
        stages_through_shot = production_stages[:4]
    completed_stages2 = await build_completed_stages_json(db, stages_through_shot)

    tx2 = None
    if target_sec is not None:
        existing_tx2 = await db.scalar(
            select(StockTransaction)
            .where(
                StockTransaction.product_id == rem2_prod.id,
                StockTransaction.to_location_id == target_sec.id,
                StockTransaction.reason == Reason.MANUAL_IN
            )
            .limit(1)
        )
        if existing_tx2:
            tx2 = existing_tx2
        else:
            if seed_action is None:
                seed_action = await action_journal_service.log(
                    db, action_type="seed_demo",
                )
            tx2 = await stock_service.record(db, StockCommand(
                product_id=rem2_prod.id,
                quantity=Decimal("80.000"),
                reason=Reason.MANUAL_IN,
                to_location_id=target_sec.id,
                quality_state=QualityState.GOOD,
                created_by=actor_id,
                comment="Demo stock for remainder 2",
                action_id=seed_action.id,
            ))
            stats["remainders"] += 1

    # 6. Create defects (только если остатки попали в PREP — иначе привязка неуместна)
    if prep_stock is None:
        await db.flush()
        return stats

    # Defect 1: Open defect for ЮП-100-2700-BL on DRILL stage.
    if drill_stage is None:
        drill_stage = production_stages[0] if production_stages else None
    if drill_stage is not None and tx1 is not None:
        existing_def1 = await db.scalar(
            select(Defect)
            .where(Defect.product_id == rem1_prod.id, Defect.route_stage_id == drill_stage.id, Defect.stock_transaction_id == tx1.id)
            .limit(1)
        )
        if not existing_def1:
            def1 = Defect(
                product_id=rem1_prod.id,
                section_id=drill_stage.section_id,
                task_id=None,
                route_stage_id=drill_stage.id,
                stock_transaction_id=tx1.id,
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

    # Defect 2: Open defect for АТ-200-2700-AN on ANOD stage.
    if anod_stage is None and len(production_stages) > 4:
        anod_stage = production_stages[4]
    if anod_stage is None and production_stages:
        anod_stage = production_stages[-1]
    if anod_stage is not None and tx2 is not None:
        existing_def2 = await db.scalar(
            select(Defect)
            .where(Defect.product_id == rem2_prod.id, Defect.route_stage_id == anod_stage.id, Defect.stock_transaction_id == tx2.id)
            .limit(1)
        )
        if not existing_def2:
            def2 = Defect(
                product_id=rem2_prod.id,
                section_id=anod_stage.section_id,
                task_id=None,
                route_stage_id=anod_stage.id,
                stock_transaction_id=tx2.id,
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
