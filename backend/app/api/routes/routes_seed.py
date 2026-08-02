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
    defect_types: int


class SeedPreview(BaseModel):
    """Counts that would be created from seed files (without touching DB)."""
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int
    sections: int
    section_operations: int
    defect_types: int


def _defect_types() -> list:
    """Справочник типов брака из канона (тикет #25)."""
    from app.seeds.canon.quality_data import DEFECT_TYPES

    return DEFECT_TYPES


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
        defect_types=len(_defect_types()),
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
            defect_types=result["defect_types"],
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
        "rework_tasks", "transfers", "transfer_discrepancies", "stock_transactions", "stock_balances",
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
    """Выборочно удалить таблицы базы данных в порядке, удовлетворяющем ограничениям внешних ключей."""
    if not payload.tables:
        return

    # Защита: разрешены только определенные системные таблицы для предотвращения SQL-инъекций
    allowed_tables = {
        "defects", "defect_decisions", "defect_items", "transfer_discrepancy_defect_items",
        "rework_tasks", "transfers", "transfer_discrepancies", "stock_transactions", "stock_balances",
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
        # Порядок удаления снизу вверх для соблюдения ограничений внешних ключей.
        # Важен для NOT NULL FK (например, transfers.from_task_id / to_task_id
        # -> work_tasks.id) — обнулить их нельзя, значит transfers должны быть
        # удалены ДО work_tasks.
        ordered_tables = [
            "transfer_discrepancy_defect_items",
            "defect_items",
            "defect_decisions",
            "rework_tasks",
            "transfer_discrepancies",
            "stock_balances",
            "stock_transactions",
            "transfers",
            "defects",
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

        # Карта nullable FK-колонок: target_table -> [(ref_table, fk_col), ...].
        # Перед удалением target_table обнуляем nullable FK во всех остальных
        # cleanup-таблицах, которые на неё ссылаются. Это покрывает выборочную
        # очистку, когда пользователь выбрал target, но не выбрал ссылающуюся
        # таблицу (или наоборот). NOT NULL FK нельзя обнулить — для них порядок
        # удаления в ordered_tables гарантирует, что child удаляется раньше
        # parent. FK с ondelete="SET NULL" в схеме (defects.route_stage_id)
        # обнуляются Postgres'ом автоматически и здесь не перечислены.
        NULLABLE_FK_REFS: dict[str, list[tuple[str, str]]] = {
            "transfers": [
                ("stock_transactions", "transfer_id"),
            ],
            "stock_transactions": [
                ("defects", "stock_transaction_id"),
                ("stock_transactions", "compensates_tx_id"),
            ],
            "work_tasks": [
                ("defects", "task_id"),
                ("stock_transactions", "task_id"),
            ],
            "section_plan_lines": [
                ("stock_transactions", "section_plan_line_id"),
            ],
            "release_batches": [
                ("internal_plans", "release_batch_id"),
            ],
            "plan_positions": [
                ("plan_change_items", "plan_position_id"),
            ],
            "import_batches": [
                ("plan_change_sets", "import_batch_id"),
                ("plan_positions", "import_batch_id"),
            ],
            "route_stages": [
                ("internal_plans", "route_stage_id"),
            ],
            "route_rule_profiles": [
                ("import_batches", "rule_profile_id"),
                ("plan_positions", "route_profile_id"),
                ("route_selection_rules", "profile_id"),
            ],
            "production_routes": [
                ("plan_positions", "route_id"),
            ],
            "import_templates": [
                ("import_batches", "template_id"),
                ("route_rule_profiles", "import_template_id"),
                ("production_routes", "import_template_id"),
            ],
            "sections": [
                ("defects", "responsible_section_id"),
                ("defect_decisions", "target_section_id"),
                ("route_stages", "section_id"),
                ("route_stages", "storage_section_id"),
            ],
        }

        if "sections" in payload.tables:
            # Разрываем связи с пользователями перед удалением участков
            await db.execute(text("UPDATE users SET section_id = NULL"))
            try:
                await db.execute(text("DELETE FROM user_sections"))
            except Exception:
                pass

        deleted_tables: list[str] = []
        for table in ordered_tables:
            if table not in payload.tables:
                continue
            # Перед удалением обнуляем nullable FK из других cleanup-таблиц,
            # ссылающиеся на эту. Покрывает выборочную очистку.
            for ref_table, fk_col in NULLABLE_FK_REFS.get(table, []):
                await db.execute(
                    text(
                        f"UPDATE {ref_table} SET {fk_col} = NULL "
                        f"WHERE {fk_col} IS NOT NULL"
                    )
                )
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
