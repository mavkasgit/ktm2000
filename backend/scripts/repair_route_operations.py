#!/usr/bin/env python
"""Починка операций у маршрутов, записанных при рассинхроне правил отбора.

Что чинится
-----------
Расширение правил отбора (`route_selection_rules.actions[].group_code`) когда-то
было записано с групповыми кодами `PRESS`/`ANOD`, которых в справочнике
`section_operations` нет (там `PRESSING`/`ANODIZING`). Пока правила были такими,
сборка маршрута падала на дефолт группы: в каждый `ANODIZING`-этап попадала
первая операция группы (`ANOD_01` — «Серебро»), в `PRESSING` — `PRESS_COMB`
(«Гребенка»), а слоты `press_op`/`color` в имени маршрута оставались пустыми.
Имена маршрутов остались правдивыми, состав этапов — нет.

Маршруты импорта неизменяемы по идентичности (#230): имя/код — производные
сигнатуры, а сигнатура считается по этапам. Поэтому маршрут пересобирается
**на месте** — идентификатор сохраняется, позиции плана, строки участков,
задания и выпуски продолжают ссылаться на тот же маршрут; меняются только
операции/признаки этапов, имя и код, и пересчитывается сигнатура.

Вход для пересборки — `plan_positions.source_payload` позиции, ссылающейся на
маршрут (в маршруте payload не хранится). После починки скрипт проверяет, что
сигнатура, посчитанная по записанным этапам, равна сигнатуре пересборки: иначе
маршрут не считается починенным и его правки откатываются.

Запуск (из `backend/`):

    python scripts/repair_route_operations.py            # посмотреть, что изменится
    python scripts/repair_route_operations.py --apply    # записать

Скрипт идемпотентен: на починенных маршрутах изменений не находит.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.production_plan import PlanPosition  # noqa: E402
from app.models.route import ProductionRoute, RouteOperation, RouteStage, RouteRuleProfile  # noqa: E402
from app.services.route_builder import (  # noqa: E402
    RouteBuildBatchCache,
    build_route_from_profile,
    load_route_build_batch_cache,
)
from app.services.route_signature import (  # noqa: E402
    auto_route_code,
    encode_signature,
    refresh_route_signature,
    signature_steps_from_stages,
)


@dataclass
class RouteRepair:
    route_id: int
    route_name: str
    changed: bool = False
    reason: str | None = None
    new_name: str | None = None
    op_changes: list[str] = field(default_factory=list)


def _desired_stages(built, cache: RouteBuildBatchCache) -> list[dict]:
    """Этапы, которые записал бы импорт: шаги подряд одного участка — один этап.

    Транзитный этап несёт единственную операцию-заглушку ``Хранение: <участок>``
    (``operation_code IS NULL``) — та же строка, что пишет импорт, поэтому она
    входит и в сравнение, и в сигнатуру.
    """
    stages: list[dict] = []
    for step in sorted(built.steps, key=lambda s: s.sequence):
        section = cache.sections_by_code.get(step.section_code or "")
        if section is None:
            return []
        key = (None, section.id) if step.stage_kind == "transit" else (section.id, None)
        if not stages or stages[-1]["key"] != key:
            stages.append({"key": key, "ops": [], "steps": []})
        stages[-1]["ops"].append((step.operation_code, step.operation_name))
        stages[-1]["steps"].append(step)
    for stage in stages:
        stage["is_significant"] = any(step.is_significant for step in stage["steps"])
        stage["transforms_dimensions"] = any(step.transforms_dimensions for step in stage["steps"])
        stage["is_final"] = any(step.is_final for step in stage["steps"])
    return stages


def _existing_stages(route: ProductionRoute) -> list[dict]:
    stages: list[dict] = []
    for stage in sorted(route.stages, key=lambda s: s.sequence):
        key = (None, stage.storage_section_id) if stage.section_id is None else (stage.section_id, None)
        stages.append(
            {
                "key": key,
                "ops": [
                    (op.operation_code, op.operation_name)
                    for op in sorted(stage.operations, key=lambda op: op.sequence)
                ],
                "is_significant": stage.is_significant,
                "transforms_dimensions": stage.transforms_dimensions,
                "is_final": stage.is_final,
                "stage": stage,
            }
        )
    return stages


async def _repair_route(
    db,
    route: ProductionRoute,
    built,
    cache: RouteBuildBatchCache,
    execute: bool,
) -> RouteRepair:
    report = RouteRepair(route_id=route.id, route_name=route.name)
    desired = _desired_stages(built, cache)
    existing = _existing_stages(route)
    if [item["key"] for item in desired] != [item["key"] for item in existing]:
        have_keys = [key for item in existing for key in item["key"] if key]
        want_keys = [key for item in desired for key in item["key"] if key]
        report.reason = (
            "состав этапов расходится — нужен разбор вручную: "
            f"в базе {len(existing)} этапов, пересборка даёт {len(desired)}"
            f" (нет в базе: {sorted(set(want_keys) - set(have_keys))},"
            f" лишние в базе: {sorted(set(have_keys) - set(want_keys))})"
        )
        return report
    for want, have in zip(desired, existing):
        if want["ops"] != have["ops"]:
            report.op_changes.append(
                f"{have['stage'].section_id or have['stage'].storage_section_id}: "
                f"{[name for _code, name in have['ops']]} → {[name for _code, name in want['ops']]}"
            )
        for flag in ("is_significant", "transforms_dimensions", "is_final"):
            if want[flag] != have[flag]:
                report.op_changes.append(f"{have['stage'].sequence}: {flag} {have[flag]} → {want[flag]}")
    if built.name != route.name:
        report.new_name = built.name
    if (route.route_signature or None) != built.signature:
        report.op_changes.append(
            f"route_signature: {route.route_signature!r} → {built.signature!r}"
        )
    if not report.op_changes and report.new_name is None:
        return report

    report.changed = True
    if not execute:
        return report

    new_code = auto_route_code(built.signature)
    if new_code is not None:
        taken_by = await db.scalar(
            select(ProductionRoute.id).where(
                ProductionRoute.code == new_code, ProductionRoute.id != route.id
            )
        )
        if taken_by is not None:
            report.changed = False
            report.reason = f"код {new_code} уже занят маршрутом #{taken_by}"
            return report

    for want, have in zip(desired, existing):
        stage: RouteStage = have["stage"]
        if want["ops"] != have["ops"]:
            # Коллекция, а не `db.add`: сигнатура маршрута считается по
            # `stage.operations` из памяти, и добавление в сессию мимо
            # коллекции оставило бы в сохранённой сигнатуре прежние операции.
            stage.operations = [
                RouteOperation(
                    sequence=index,
                    operation_code=code,
                    operation_name=name,
                )
                for index, (code, name) in enumerate(want["ops"], start=1)
            ]
        for flag in ("is_significant", "transforms_dimensions", "is_final"):
            setattr(stage, flag, want[flag])
    await db.flush()

    if report.new_name:
        route.name = report.new_name
    route.code = new_code
    await refresh_route_signature(db, route)
    await db.flush()

    # Проверка читает этапы из базы, а не из памяти: без populate_existing
    # сессия вернула бы те же объекты с прежними коллекциями операций.
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route.id)
            .options(
                selectinload(RouteStage.operations),
                selectinload(RouteStage.section),
                selectinload(RouteStage.storage_section),
            )
            .order_by(RouteStage.sequence)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    actual = encode_signature(signature_steps_from_stages(stages))
    if actual != built.signature:
        report.changed = False
        report.reason = "сигнатура после починки не совпала со пересборкой — правки отменены"
        raise RuntimeError(report.reason)
    return report


async def main() -> None:
    execute = "--apply" in sys.argv
    async with async_session() as db:
        rows = (
            await db.execute(
                select(ProductionRoute, PlanPosition)
                .join(PlanPosition, PlanPosition.route_id == ProductionRoute.id)
                .where(PlanPosition.route_profile_id.isnot(None))
                .options(
                    selectinload(ProductionRoute.stages).selectinload(RouteStage.operations),
                )
                .order_by(ProductionRoute.id)
            )
        ).all()
        routes: dict[int, ProductionRoute] = {}
        payloads_by_route: dict[int, list[PlanPosition]] = {}
        for route, position in rows:
            routes.setdefault(route.id, route)
            candidates = payloads_by_route.setdefault(route.id, [])
            if all(item.source_row_hash != position.source_row_hash for item in candidates):
                candidates.append(position)

        caches: dict[int, tuple[RouteRuleProfile, RouteBuildBatchCache]] = {}
        products: dict[int, Product] = {}
        reports: list[RouteRepair] = []
        skipped: list[tuple[int, str]] = []

        for route_id, route in sorted(routes.items()):
            candidates = payloads_by_route[route_id]
            profile_id = next(
                (item.route_profile_id for item in candidates if item.route_profile_id is not None),
                None,
            )
            if profile_id is None:
                skipped.append((route_id, "у позиций маршрута нет профиля отбора"))
                continue
            if profile_id not in caches:
                profile = await db.get(RouteRuleProfile, profile_id)
                if profile is None:
                    skipped.append((route_id, f"профиль #{profile_id} не найден"))
                    continue
                caches[profile_id] = (
                    profile,
                    await load_route_build_batch_cache(db, profile),
                )
            profile, cache = caches[profile_id]
            existing_keys = [item["key"] for item in _existing_stages(route)]
            try:
                async with db.begin_nested():
                    # Строка-источник подбирается по составу этапов: у одного
                    # маршрута могут стоять позиции с разным payload (сверловка
                    # против окон), и «первая попавшаяся» дала бы ложное
                    # расхождение состава.
                    chosen: tuple[PlanPosition, object] | None = None
                    fallback: tuple[PlanPosition, object] | None = None
                    for position in candidates:
                        payload = dict(position.source_payload or {})
                        if position.product_id is not None:
                            if position.product_id not in products:
                                products[position.product_id] = await db.get(
                                    Product, position.product_id
                                )
                            product = products[position.product_id]
                            payload["product_id"] = position.product_id
                        else:
                            product = None
                        built = await build_route_from_profile(
                            db, profile, payload, None, product=product, batch=cache
                        )
                        if built.error or not built.name:
                            continue
                        if fallback is None:
                            fallback = (position, built)
                        if [item["key"] for item in _desired_stages(built, cache)] == existing_keys:
                            chosen = (position, built)
                            break
                    _position, built = chosen or fallback or (None, None)
                    if built is None:
                        skipped.append((route_id, "ни одна позиция маршрута не пересобирается"))
                        continue
                    reports.append(await _repair_route(db, route, built, cache, execute))
            except Exception as exc:  # noqa: BLE001 — отчёт важнее падения всего прогона
                skipped.append((route_id, f"ошибка: {exc}"))

        changed = [report for report in reports if report.changed]
        for report in reports:
            mark = "ИЗМЕНИТЬ" if report.changed else "ok"
            print(f"#{report.route_id:>3} [{mark}] {report.route_name!r}"
                  + (f" → {report.new_name!r}" if report.new_name else "")
                  + (f" ({report.reason})" if report.reason else ""))
            for change in report.op_changes:
                print(f"        {change}")
        for route_id, reason in skipped:
            print(f"#{route_id:>3} [ПРОПУСК] {reason}")
        print(f"\nмаршрутов к починке: {len(changed)} из {len(reports)} (ещё {len(skipped)} пропущено)")
        if execute:
            await db.commit()
            print("применено")
        else:
            print("сухой прогон (нужен --apply, чтобы записать)")


if __name__ == "__main__":
    asyncio.run(main())
