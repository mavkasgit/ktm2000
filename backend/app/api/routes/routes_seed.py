"""Seed endpoint — fills ALL reference data in one shot:
ImportTemplate + RouteRuleProfile + Routes + SelectionRules."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WRITER_ROLES, require_role, get_current_user
from app.models.user import User
from app.core.config import settings
from app.core.database import get_db
from app.seeds.run_seed import run_full_seed
from app.seeds.seeders.users_seeder import seed_users
from app.seeds.seeders.demo_production_seeder import seed_demo_production
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
from app.services.audit_log_service import log_action
from app.models.audit_log import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes-seed", tags=["routes-seed"])


class SeedSummary(BaseModel):
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int
    sections: int
    section_operations: int


class UserSeedResult(BaseModel):
    user_id: int
    email: str


@router.post("/reseed-system-user", response_model=UserSeedResult, dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def reseed_system_user(db: AsyncSession = Depends(get_db)) -> UserSeedResult:
    """Delete and recreate system user with id=1. Ensures FK constraints work with _fake_user()."""
    try:
        result = await seed_users(db)
        await db.commit()
        user_id, user = next(iter(result.items()))
        return UserSeedResult(user_id=user_id, email=user.email)
    except Exception as e:
        await db.rollback()
        logger.exception("Reseed system user failed")
        raise HTTPException(status_code=500, detail=str(e))


class SeedPreview(BaseModel):
    """Counts that would be created from seed files (without touching DB)."""
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int
    sections: int
    section_operations: int


@router.get("/preview", response_model=SeedPreview)
async def seed_preview() -> SeedPreview:
    """Return counts from seed files without touching the database."""
    from app.seeds.import_templates import IMPORT_TEMPLATES
    from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
    from app.seeds.routes import ROUTES
    from app.seeds.selection_rules import SELECTION_RULES

    # Sections and operations are defined in the seeder itself
    from app.seeds.seeders.sections_seeder import SECTIONS_DATA, SECTION_OPS

    # Count total operations (skip None placeholders)
    total_ops = sum(
        1 for ops in SECTION_OPS.values()
        for op in ops
        if op[3] is not None  # op_code is index 3
    )

    return SeedPreview(
        import_templates=len(IMPORT_TEMPLATES),
        route_rule_profiles=len(ROUTE_RULE_PROFILES),
        # Static routes + 1 dynamic route per profile with route_sections
        routes=len(ROUTES) + sum(1 for p in ROUTE_RULE_PROFILES if p.get("route_sections")),
        selection_rules=len(SELECTION_RULES),
        sections=len(SECTIONS_DATA),
        section_operations=total_ops,
    )


@router.post("", response_model=SeedSummary, status_code=status.HTTP_201_CREATED)
async def seed_all(
    force: bool = Query(False, description="Force replace routes and dependent data"),
    db: AsyncSession = Depends(get_db),
) -> SeedSummary:
    """Seed all reference data: templates, profiles, routes, selection rules."""
    if force and settings.ENV in ("prod", "production"):
        raise HTTPException(status_code=403, detail="force=true is not allowed in production")
    try:
        result = await run_full_seed(db, force=force)
        await db.commit()
        return SeedSummary(
            import_templates=result["import_templates"],
            route_rule_profiles=result["route_rule_profiles"],
            routes=result["routes"],
            selection_rules=result["selection_rules"],
            sections=result["sections"],
            section_operations=result["section_operations"],
        )
    except RuntimeError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Seed failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class DemoSeedSummary(BaseModel):
    products: int
    remainders: int
    defects: int


@router.post("/demo-production", response_model=DemoSeedSummary, status_code=status.HTTP_201_CREATED)
async def seed_demo_production_endpoint(
    db: AsyncSession = Depends(get_db),
) -> DemoSeedSummary:
    """Seed only demo production data (remainders, stages, defects)."""
    try:
        stats = await seed_demo_production(db)
        await db.commit()
        return DemoSeedSummary(
            products=stats.get("products", 0),
            remainders=stats.get("remainders", 0),
            defects=stats.get("defects", 0),
        )
    except Exception as e:
        logger.exception("Demo seed failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class ClearSummary(BaseModel):
    cleanup: dict


@router.post("/clear-demo-production", response_model=ClearSummary)
async def clear_demo_production_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ClearSummary:
    """Clear generated production data (remainders, defects, tasks, etc.)."""
    try:
        stats = await clear_generated_production_data(db)
        await db.commit()
        return ClearSummary(cleanup=stats)
    except Exception as e:
        logger.exception("Clear production data failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class CleanupStatsResponse(BaseModel):
    stats: dict[str, int]


class CleanupRequest(BaseModel):
    tables: list[str]


@router.get("/cleanup-stats", response_model=CleanupStatsResponse)
async def cleanup_stats_endpoint(
    db: AsyncSession = Depends(get_db),
) -> CleanupStatsResponse:
    """Подсчитать количество записей во всех таблицах, доступных для очистки."""
    tables = [
        "defects", "defect_decisions", "defect_items", "transfer_discrepancy_defect_items",
        "rework_tasks", "transfers", "transfer_discrepancies", "movements", "spg_remainders",
        "work_tasks", "section_plan_lines", "internal_plans", "release_batch_positions", "release_batches",
        "plan_change_items", "plan_change_sets", "plan_positions", "import_batches", "production_plans",
        "import_files", "production_routes", "route_stages", "route_operations", "route_rule_profiles",
        "route_selection_rules", "route_matching_rules", "route_rule_conditions", "import_templates",
        "sections", "section_operations"
    ]
    stats = {}
    for table in tables:
        try:
            res = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
            stats[table] = res.scalar() or 0
        except Exception as e:
            logger.warning(f"Failed to get row count for table {table}: {e}")
            stats[table] = 0
    return CleanupStatsResponse(stats=stats)


@router.post("/cleanup", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def cleanup_endpoint(
    payload: CleanupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Выборочно удалить таблицы базы данных с использованием TRUNCATE CASCADE."""
    if not payload.tables:
        return

    # Защита: разрешены только определенные системные таблицы для предотвращения SQL-инъекций
    allowed_tables = {
        "defects", "defect_decisions", "defect_items", "transfer_discrepancy_defect_items",
        "rework_tasks", "transfers", "transfer_discrepancies", "movements", "spg_remainders",
        "work_tasks", "section_plan_lines", "internal_plans", "release_batch_positions", "release_batches",
        "plan_change_items", "plan_change_sets", "plan_positions", "import_batches", "production_plans",
        "import_files", "production_routes", "route_stages", "route_operations", "route_rule_profiles",
        "route_selection_rules", "route_matching_rules", "route_rule_conditions", "import_templates",
        "sections", "section_operations"
    }

    invalid_tables = [t for t in payload.tables if t not in allowed_tables]
    if invalid_tables:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимые таблицы для очистки: {', '.join(invalid_tables)}"
        )

    try:
        # Порядок удаления снизу вверх для соблюдения ограничений внешних ключей
        ordered_tables = [
            "transfer_discrepancy_defect_items",
            "defect_decisions",
            "defect_items",
            "rework_tasks",
            "defects",
            "transfer_discrepancies",
            "transfers",
            "movements",
            "spg_remainders",
            "work_tasks",
            "section_plan_lines",
            "internal_plans",
            "release_batch_positions",
            "release_batches",
            "plan_change_items",
            "plan_change_sets",
            "plan_positions",
            "import_batches",
            "production_plans",
            "import_files",
            "route_rule_conditions",
            "route_matching_rules",
            "route_operations",
            "route_stages",
            "route_selection_rules",
            "route_rule_profiles",
            "production_routes",
            "import_templates",
            "section_operations",
            "sections"
        ]

        if "sections" in payload.tables:
            # Разрываем связи с пользователями перед удалением участков
            await db.execute(text("UPDATE users SET section_id = NULL"))
            try:
                await db.execute(text("DELETE FROM user_sections"))
            except Exception:
                pass

        if "import_templates" in payload.tables:
            await db.execute(text("UPDATE route_rule_profiles SET import_template_id = NULL"))
            await db.execute(text("UPDATE import_batches SET template_id = NULL"))

        if "route_rule_profiles" in payload.tables:
            await db.execute(text("UPDATE import_batches SET rule_profile_id = NULL"))

        deleted_tables = []
        for table in ordered_tables:
            if table in payload.tables:
                await db.execute(text(f"DELETE FROM {table}"))
                deleted_tables.append(table)
        
        # Запись лога аудита
        await log_action(
            db,
            status="success",
            title="Выборочная очистка данных",
            message=f"Успешно удалены таблицы: {', '.join(deleted_tables)}.",
            user=current_user,
            action=AuditAction.DELETE,
        )
        await db.commit()
    except Exception as e:
        logger.exception("Selective cleanup failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
