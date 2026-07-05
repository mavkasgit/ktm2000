import sys
import os
import time
import json
import asyncio
import argparse
from pathlib import Path
from decimal import Decimal
from contextlib import contextmanager

# Добавляем путь к backend, чтобы работал импорт app
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, async_session
from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanSourceType,
    ProductionPlan,
    PlanChangeSet,
    PlanChangeItem,
)
from app.models.route import ProductionRoute, RouteRuleProfile, RouteSelectionRule, RouteStage, SectionOperation
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.services.plan_import_service import _make_change_items
from app.services.excel_import import ParsedPlanRow
from app.api.routes.production_plans import section_totals
from app.services.production_plan_service import apply_change_set

RESULTS_FILE = Path(__file__).parent / "before_results.json"

class QueryCounter:
    def __init__(self):
        self.count = 0

    def increase(self, *args, **kwargs):
        self.count += 1

@contextmanager
def count_queries():
    counter = QueryCounter()
    event.listen(engine.sync_engine, "before_cursor_execute", counter.increase)
    try:
        yield counter
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", counter.increase)

async def seed_data(session: AsyncSession):
    """Инициализация необходимых тестовых справочников."""
    # 1. Секции
    sections_def = [
        {"code": "RAW_STOCK", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
        {"code": "ANODIZING", "name": "Анодирование", "sort_order": 50, "kind": "production"},
        {"code": "PACKING", "name": "Упаковка", "sort_order": 80, "kind": "production"},
        {"code": "FINISHED_STOCK", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock"},
    ]
    
    sections = {}
    for item in sections_def:
        sec = await session.scalar(select(Section).where(Section.code == item["code"]))
        if not sec:
            sec = Section(
                code=item["code"],
                name=item["name"],
                sort_order=item["sort_order"],
                kind=item["kind"],
                is_active=True,
            )
            session.add(sec)
            await session.flush()
        sections[item["code"]] = sec

    # 2. Операции для ANOD и PACK
    anod_sec = sections["ANODIZING"]
    op_anod = await session.scalar(select(SectionOperation).where(SectionOperation.operation_code == "ANOD_BENCH"))
    if not op_anod:
        session.add(SectionOperation(
            section_id=anod_sec.id,
            operation_code="ANOD_BENCH",
            operation_name="Бенчмарк анодирование",
            group_code="ANOD",
            group_name="Анодирование",
            is_significant=True,
            sort_order=1,
        ))
        
    pack_sec = sections["PACKING"]
    op_pack = await session.scalar(select(SectionOperation).where(SectionOperation.operation_code == "PACK_BENCH"))
    if not op_pack:
        session.add(SectionOperation(
            section_id=pack_sec.id,
            operation_code="PACK_BENCH",
            operation_name="Бенчмарк упаковка",
            group_code="PACK",
            group_name="Упаковка",
            is_significant=False,
            sort_order=1,
        ))
    await session.flush()

    # 3. Шаблон импорта
    template = await session.scalar(select(ImportTemplate).where(ImportTemplate.code == "bench_template"))
    if not template:
        template = ImportTemplate(
            code="bench_template",
            name="Шаблон для бенчмарков",
            is_active=True,
        )
        session.add(template)
        await session.flush()

    # 4. Профиль правил и правила
    profile = await session.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == "bench_profile"))
    if not profile:
        profile = RouteRuleProfile(
            code="bench_profile",
            name="Профиль для бенчмарков",
            is_active=True,
            priority=1000,
            import_template_id=template.id,
            route_sections=["RAW_STOCK", "ANODIZING", "PACKING", "FINISHED_STOCK"],
        )
        session.add(profile)
        await session.flush()

        # Правило выбора маршрута
        rule = RouteSelectionRule(
            code="bench_rule",
            name="Бенчмарк правило выбора",
            profile_id=profile.id,
            priority=1000,
            phase="route_select",
            conditions=[],
            actions=[
                {"action_type": "require_section", "section_code": "ANODIZING"},
                {"action_type": "require_section", "section_code": "PACKING"},
            ],
        )
        session.add(rule)
        await session.flush()

    # 5. Продукт и техкарта
    product = await session.scalar(select(Product).where(Product.sku == "BENCH-PROD"))
    if not product:
        product = Product(
            sku="BENCH-PROD",
            name="Продукт для бенчмарков",
            type=ProductType.finished_good,
            unit="pcs",
            quantity_per_hanger=10,
        )
        session.add(product)
        await session.flush()

    techcard = await session.scalar(select(Techcard).where(Techcard.product_id == product.id))
    if not techcard:
        techcard = Techcard(
            product_id=product.id,
            version="v_bench",
            is_active=True,
        )
        session.add(techcard)
        await session.flush()

        # Компонент для техкарты
        comp = Product(
            sku="BENCH-PROD-RAW",
            name="Сырье для бенчмарка",
            type=ProductType.component,
            unit="pcs",
        )
        session.add(comp)
        await session.flush()

        line = TechcardLine(
            techcard_id=techcard.id,
            component_product_id=comp.id,
            quantity=1,
            unit="pcs",
        )
        session.add(line)
        await session.flush()

    # 6. Создаем ProductionRoute, который совпадает с секциями
    # Это нужно для сценариев сопоставления маршрутов
    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.name == "Dynamic: bench_profile"))
    if not route:
        route = ProductionRoute(
            name="Dynamic: bench_profile",
            is_active=True,
            import_template_id=template.id,
        )
        session.add(route)
        await session.flush()

        # Добавим этапы маршрута
        for idx, sec_code in enumerate(["WH", "ANOD", "PACK", "FG_WH"], start=1):
            stage = RouteStage(
                route_id=route.id,
                section_id=sections[sec_code].id,
                sequence=idx,
            )
            session.add(stage)
        await session.flush()

    return {
        "product": product,
        "profile": profile,
        "template": template,
        "route": route,
    }

def generate_parsed_rows(sku: str, count: int) -> list[ParsedPlanRow]:
    return [
        ParsedPlanRow(
            source_row_numbers=[i],
            source_sku=sku,
            source_name=f"Продукт {sku} {i}",
            quantity=Decimal("100"),
            source_ref=f"ref_{i}",
            source_fingerprint=f"fingerprint_{i}",
            source_row_hash=f"hash_{i}",
            payload={"color": "серебро", "length": 2.7},
            warnings=[],
            errors=[]
        )
        for i in range(1, count + 1)
    ]

async def run_benchmark_for_size(session: AsyncSession, seeded: dict, size: int):
    product = seeded["product"]
    profile = seeded["profile"]
    template = seeded["template"]
    route = seeded["route"]

    parsed_rows = generate_parsed_rows(product.sku, size)
    products_by_sku = {product.sku.lower(): product}

    # --- Сценарий 1: Импорт (создание change items) ---
    # Мы замеряем время и SQL-запросы для _make_change_items
    start_time = time.perf_counter()
    with count_queries() as counter:
        await _make_change_items(
            session,
            change_set_id=1,
            parsed_rows=parsed_rows,
            products_by_sku=products_by_sku,
            mode="create_plan",
            existing_positions=[],
            rule_profile_id=profile.id,
            template_id=template.id,
            template_column_mapping=None,
            normalize_hanger_quantity=True,
        )
    import_time = time.perf_counter() - start_time
    import_queries = counter.count

    # --- Сценарий 2: Section Totals ---
    # Создаем план и сохраняем позиции, чтобы рассчитать итоги
    plan = ProductionPlan(plan_no=f"BENCH-{size}", name=f"Benchmark Plan {size}")
    session.add(plan)
    await session.flush()

    positions = []
    for i, row in enumerate(parsed_rows, start=1):
        pos = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.excel_import,
            source_sku=row.source_sku,
            source_name=row.source_name,
            quantity=row.quantity,
            status="draft",
            validation_status="valid",
            source_row_number=i,
            source_payload=row.payload,
            route_id=route.id,
            route_profile_id=profile.id,
            route_origin="auto",
        )
        session.add(pos)
        positions.append(pos)
    await session.flush()

    start_time = time.perf_counter()
    with count_queries() as counter:
        # Вызываем section_totals для нашего плана
        await section_totals(production_plan_id=plan.id, db=session)
    totals_time = time.perf_counter() - start_time
    totals_queries = counter.count

    # --- Сценарий 3: Применение изменений (update draft positions с валидацией) ---
    # 1. Создаем отдельный план
    apply_plan = ProductionPlan(plan_no=f"BENCH-APPLY-{size}", name=f"Apply Benchmark Plan {size}")
    session.add(apply_plan)
    await session.flush()

    # 2. Создаем черновики позиций
    draft_positions = []
    for i, row in enumerate(parsed_rows, start=1):
        pos = PlanPosition(
            production_plan_id=apply_plan.id,
            product_id=product.id,
            source_type=PlanSourceType.excel_import,
            source_sku=row.source_sku,
            source_name=row.source_name,
            quantity=row.quantity,
            status="draft",
            validation_status="valid",
            source_row_number=i,
            source_payload=row.payload,
            route_id=route.id,
            route_profile_id=profile.id,
            route_origin="auto",
            source_fingerprint=row.source_fingerprint,
            source_row_hash=row.source_row_hash,
        )
        session.add(pos)
        draft_positions.append(pos)
    await session.flush()

    # 3. Создаем пакет изменений (change set)
    change_set = PlanChangeSet(
        production_plan_id=apply_plan.id,
        status="draft",
        summary={},
    )
    session.add(change_set)
    await session.flush()

    # 4. Создаем элементы изменений (change items) типа update_draft_position
    for pos in draft_positions:
        item = PlanChangeItem(
            change_set_id=change_set.id,
            change_action="update_draft_position",
            plan_position_id=pos.id,
            source_row_number=pos.source_row_number,
            status="pending",
            errors=[],
            warnings=[],
            before_data={"quantity": str(pos.quantity)},
            after_data={
                "product_id": pos.product_id,
                "source_sku": pos.source_sku,
                "source_name": pos.source_name,
                "quantity": str(pos.quantity + Decimal("10")),
                "source_payload": pos.source_payload,
                "source_ref": pos.source_ref,
                "source_fingerprint": pos.source_fingerprint,
                "source_row_hash": pos.source_row_hash,
                "route_id": pos.route_id,
                "route_profile_id": pos.route_profile_id,
                "route_origin": "auto",
            }
        )
        session.add(item)

    await session.flush()

    # 5. Замеряем apply_change_set
    start_time = time.perf_counter()
    with count_queries() as counter:
        await apply_change_set(session, change_set.id)
    apply_time = time.perf_counter() - start_time
    apply_queries = counter.count

    return {
        "import": {"time_sec": import_time, "queries": import_queries},
        "totals": {"time_sec": totals_time, "queries": totals_queries},
        "apply": {"time_sec": apply_time, "queries": apply_queries},
    }

async def run_benchmarks():
    async with async_session() as session:
        # Мы запускаем все в одной транзакции и откатываем ее в конце
        seeded = await seed_data(session)
        
        print("Запуск бенчмарка для N=100...")
        results_100 = await run_benchmark_for_size(session, seeded, 100)
        
        print("Запуск бенчмарка для N=500...")
        results_500 = await run_benchmark_for_size(session, seeded, 500)
        
        await session.rollback()

    return {
        "100": results_100,
        "500": results_500,
    }

def print_table(before: dict, after: dict | None = None):
    print("\n=== РЕЗУЛЬТАТЫ БЕНЧМАРКА ===")
    scenarios = ["import", "totals", "apply"]
    if after is None:
        print("| Сценарий | N | Время (сек) | SQL Запросы |")
        print("|---|---|---|---|")
        for size in ["100", "500"]:
            for sc in scenarios:
                if sc in before[size]:
                    res = before[size][sc]
                    print(f"| {sc:6} | {size} | {res['time_sec']:.4f} | {res['queries']} |")
    else:
        print("| Сценарий | N | Время Before | Время After | Ускорение | Запросы Before | Запросы After | Снижение запросов |")
        print("|---|---|---|---|---|---|---|---|")
        for size in ["100", "500"]:
            for sc in scenarios:
                # Если в before нет сценария "apply" (так как его запустили впервые после оптимизации),
                # мы покажем прочерки для Before.
                if sc not in before[size]:
                    b = {"time_sec": 0.0, "queries": 0}
                else:
                    b = before[size][sc]
                a = after[size][sc]
                
                speedup = b['time_sec'] / a['time_sec'] if a['time_sec'] > 0 and b['time_sec'] > 0 else 0
                query_reduction = (b['queries'] - a['queries']) / b['queries'] * 100 if b['queries'] > 0 else 0
                
                b_time_str = f"{b['time_sec']:.4f}s" if b['time_sec'] > 0 else "N/A"
                speedup_str = f"{speedup:.1f}x" if speedup > 0 else "N/A"
                b_queries_str = str(b['queries']) if b['queries'] > 0 else "N/A"
                reduction_str = f"{query_reduction:.1f}%" if b['queries'] > 0 else "N/A"
                
                print(f"| {sc:6} | {size} | {b_time_str} | {a['time_sec']:.4f}s | {speedup_str} | {b_queries_str} | {a['queries']} | {reduction_str} |")

async def main():
    parser = argparse.ArgumentParser(description="Бенчмарк сопоставления маршрутов.")
    parser.add_argument(
        "--mode",
        choices=["before", "after"],
        required=True,
        help="Режим: 'before' для фиксации базовых показателей, 'after' для замера и сравнения."
    )
    args = parser.parse_args()

    if args.mode == "before":
        print("Выполняются замеры 'ДО' оптимизации...")
        results = await run_benchmarks()
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Показатели 'ДО' сохранены в {RESULTS_FILE}")
        print_table(results)
    else:
        if not RESULTS_FILE.exists():
            print(f"Ошибка: Файл результатов 'ДО' ({RESULTS_FILE}) не найден. Сначала запустите с --mode before.")
            sys.exit(1)
            
        print("Выполняются замеры 'ПОСЛЕ' оптимизации...")
        after_results = await run_benchmarks()
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            before_results = json.load(f)
            
        print_table(before_results, after_results)

if __name__ == "__main__":
    asyncio.run(main())
