"""Каскадное удаление маршрута и критерий «маршрут-сирота» (#228).

Контракты, которые здесь защищаются:
* ``DELETE /routes/{id}`` без ``force`` на связанном маршруте → 409 со
  списком того, что уйдёт, включая задания (регрессия #228) — и НИЧЕГО
  в БД не меняется;
* ``?force=true`` сносит весь граф, включая операции этапов и условия
  правил привязки — «висячих» операций не остаётся;
* уборка сирот не трогает маршрут с позицией плана;
* уборка по умолчанию — dry run, удаляет только при ``execute=True``;
* сирота — маршрут, который создал ИМПОРТ: на свежей БД после ``db:seed``
  уборка с ``execute`` не сносит эталонные ``universal_rp`` / ``dynamic_*``
  (у них нет ни позиций, ни заданий, но справочный код есть);
* архивный маршрут уборке не подлежит — за архивирование отвечает человек.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, or_, select, update

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.route import (
    ProductionRoute,
    RouteMatchingRule,
    RouteOperation,
    RouteRuleCondition,
    RouteStage,
)
from app.models.work_task import WorkTask
from app.seeds.run_seed import run_full_seed
from app.services.route_deletion import cleanup_orphan_routes, find_orphan_routes
from app.services.route_signature import auto_route_code
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route

pytestmark = pytest.mark.asyncio


# ─── helpers ────────────────────────────────────────────────────────────────


async def _route_id(session: AsyncSession, name: str) -> int:
    route_id = await session.scalar(select(ProductionRoute.id).where(ProductionRoute.name == name))
    assert route_id is not None, f"Маршрут {name!r} не создан фикстурой"
    return int(route_id)


async def _add_matching_rule(session: AsyncSession, route_id: int) -> tuple[int, int]:
    """Правило привязки с одним условием — каскад обязан снести оба."""
    rule = RouteMatchingRule(route_id=route_id, priority=10)
    session.add(rule)
    await session.flush()
    condition = RouteRuleCondition(
        rule_id=rule.id, field="product_type", operator="eq", value="panel"
    )
    session.add(condition)
    await session.flush()
    return rule.id, condition.id


async def _make_orphan_route(
    session: AsyncSession, *, name: str, code: str | None, section_id: int
) -> int:
    """Маршрут, который создал импорт, но ни одна позиция его не взяла.

    ``code`` — тот, что импорт реально пишет: ``NULL`` для маршрута, созданного
    до #230, и ``auto-<хеш сигнатуры>`` после (#230, ADR-0051). Справочный код
    у такого маршрута не бывает, поэтому его и не передаём.
    """
    route = ProductionRoute(name=name, code=code, is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=section_id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"
        )
    )
    await session.commit()
    return route.id


def _auto_code(tag: str) -> str:
    """Код маршрута импорта из его сигнатуры — так же, как это делает импорт."""
    return auto_route_code(f"SAWING:SAW>{tag}:,1")


async def _count(session: AsyncSession, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_delete_linked_route_without_force_returns_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Связанный маршрут без force → 409, перечисляющий ВСЕ связи, включая задания."""
    fx = await _setup_minimal_route(session, sku="RD-409", qty=Decimal("10"))
    route_id = await _route_id(session, "R-RD-409")
    task_id = fx["task"].id

    resp = await client.delete(f"/api/routes/{route_id}")

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail.startswith("Будут удалены:"), detail
    assert "шаг(ов) маршрута" in detail, detail
    # Точные количества, а не только подстрока: регрессия #228 была в том,
    # что задания вообще не попадали в связи маршрута (0 → часть исчезает).
    assert "1 шаг(ов) маршрута" in detail, detail
    assert "1 линия(ий) плана участков" in detail, detail
    assert "1 задание(ий)" in detail, f"Зания не попали в предупреждение (#228): {detail}"
    assert "1 позиция(ий) плана" in detail, detail

    # 409 — отказ, а не «удалили и предупредили»: весь граф на месте.
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == route_id)) == 1
    assert await _count(session, select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id)) == 1
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id)
        .where(RouteStage.route_id == route_id),
    ) == 1
    assert await _count(session, select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id)) == 1
    assert await _count(session, select(func.count()).select_from(WorkTask).where(WorkTask.id == task_id)) == 1
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id)) == 1


async def test_delete_linked_route_with_force_removes_whole_graph(
    client: AsyncClient, session: AsyncSession
) -> None:
    """force=true сносит весь граф: операции этапов и условия правил в том числе."""
    fx = await _setup_minimal_route(session, sku="RD-FORCE", qty=Decimal("10"))
    route_id = await _route_id(session, "R-RD-FORCE")
    rule_id, condition_id = await _add_matching_rule(session, route_id)
    await session.commit()

    assert (
        await _count(session, select(func.count()).select_from(RouteRuleCondition).where(RouteRuleCondition.id == condition_id))
        == 1
    ), "Предусловие: условие правила создано"

    resp = await client.delete(f"/api/routes/{route_id}?force=true")

    assert resp.status_code == 204, resp.text

    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == route_id)) == 0
    assert await _count(session, select(func.count()).select_from(RouteStage).where(RouteStage.route_id == route_id)) == 0
    # Главное: операции сносились вместе с этапами, а не остались сиротами.
    assert await _count(session, select(func.count()).select_from(RouteOperation)) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id),
    ) == 0, "Остались операции без этапа"
    assert await _count(session, select(func.count()).select_from(RouteMatchingRule).where(RouteMatchingRule.id == rule_id)) == 0
    assert await _count(session, select(func.count()).select_from(RouteRuleCondition).where(RouteRuleCondition.id == condition_id)) == 0
    assert await _count(session, select(func.count()).select_from(SectionPlanLine).where(SectionPlanLine.route_id == route_id)) == 0
    assert await _count(session, select(func.count()).select_from(WorkTask).where(WorkTask.id == fx["task"].id)) == 0
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == route_id)) == 0
    # Внутренний план остался пустой оболочкой — его тоже убирают.
    assert await _count(session, select(func.count()).select_from(InternalPlan)) == 0


async def test_orphan_routes_exclude_routes_with_positions(
    session: AsyncSession,
) -> None:
    """Сирота — маршрут без позиций плана/строк/заданий; маршрут с позицией плана — не сирота."""
    fx = await _setup_minimal_route(session, sku="RD-ORPH", qty=Decimal("10"))
    linked_id = await _route_id(session, "R-RD-ORPH")
    orphan_id = await _make_orphan_route(
        session, name="RD-orphan-1", code=_auto_code("ORPH1"), section_id=fx["prod"].id
    )

    orphans = await find_orphan_routes(session)
    orphan_ids = [o.id for o in orphans]

    assert orphan_id in orphan_ids
    assert linked_id not in orphan_ids, "Маршрут с позицией плана не должен считаться сиротой"
    stages = {o.id: o.stages for o in orphans}
    assert stages[orphan_id] == 1


async def test_cleanup_orphan_routes_is_dry_run_by_default_and_executes_on_flag(
    session: AsyncSession,
) -> None:
    """Без execute уборка только читает; с execute сносит сирот вместе с этапами."""
    fx = await _setup_minimal_route(session, sku="RD-DRY", qty=Decimal("10"))
    linked_id = await _route_id(session, "R-RD-DRY")
    dry1 = await _make_orphan_route(
        session, name="RD-dry-1", code=_auto_code("DRY1"), section_id=fx["prod"].id
    )
    dry2 = await _make_orphan_route(
        session, name="RD-dry-2", code=None, section_id=fx["prod"].id
    )

    report = await cleanup_orphan_routes(session)

    assert report.executed is False
    assert report.deleted_ids == []
    assert {dry1, dry2} <= {o.id for o in report.found}
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id.in_([dry1, dry2]))) == 2

    report = await cleanup_orphan_routes(session, execute=True)

    assert report.executed is True
    assert set(report.deleted_ids) >= {dry1, dry2}
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id.in_([dry1, dry2]))) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteStage)
        .where(RouteStage.route_id.in_([dry1, dry2])),
    ) == 0
    assert await _count(
        session,
        select(func.count())
        .select_from(RouteOperation)
        .join(RouteStage, RouteOperation.route_stage_id == RouteStage.id)
        .where(RouteStage.route_id.in_([dry1, dry2])),
    ) == 0
    # Уборка не должна задеть маршрут с позицией плана.
    assert await _count(session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == linked_id)) == 1
    assert await _count(session, select(func.count()).select_from(PlanPosition).where(PlanPosition.route_id == linked_id)) == 1


async def test_cleanup_orphan_routes_keeps_seeded_reference_routes(session) -> None:
    """Уборка с execute не сносит эталонные маршруты завода.

    Регресс #228 на свежей БД: у сид-маршрутов (``universal_rp``,
    ``dynamic_*``) после ``db:seed`` нет ни позиций плана, ни заданий, и
    критерий «нет связей» считал их сиротами. Дальше уборка с ``--execute``
    удаляла их, а ``run_seed`` не восстанавливал: он находит существующие
    строки по коду и только обновляет их. Признак «маршрут создал импорт»
    (кода нет либо он ``auto-``) — обязательная часть критерия.
    """
    await run_full_seed(session, force=True)

    seeded = list(
        (
            await session.scalars(
                select(ProductionRoute).where(
                    or_(
                        ProductionRoute.code == "universal_rp",
                        ProductionRoute.code.like("dynamic_%"),
                    )
                )
            )
        ).all()
    )
    assert seeded, "Предусловие: db:seed оставил эталонные маршруты"
    seeded_ids = {route.id for route in seeded}

    # Ни у одного эталонного маршрута нет ни позиций плана, ни заданий —
    # иначе тест проверял бы не то: связанный маршрут уборка и так не тронет.
    for route in seeded:
        assert await _count(
            session,
            select(func.count())
            .select_from(WorkTask)
            .join(RouteStage, WorkTask.route_stage_id == RouteStage.id)
            .where(RouteStage.route_id == route.id),
        ) == 0, f"Предусловие: у сид-маршрута {route.code!r} нет заданий"

    orphans = await find_orphan_routes(session)
    assert not (seeded_ids & {o.id for o in orphans}), (
        "Справочный код — признак «маршрут создал не импорт»: эталонные "
        f"маршруты попали в отчёт сирот: {sorted(seeded_ids & {o.id for o in orphans})}"
    )

    report = await cleanup_orphan_routes(session, execute=True)

    assert not (seeded_ids & set(report.deleted_ids)), (
        "Уборка снесла эталонные маршруты завода — потеря данных: "
        f"{sorted(seeded_ids & set(report.deleted_ids))}"
    )
    assert await _count(
        session,
        select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id.in_(seeded_ids)),
    ) == len(seeded_ids)


async def test_orphan_criterion_skips_archived_import_route(session: AsyncSession) -> None:
    """Архивный маршрут импорта уборке не подлежит.

    Архивный маршрут назначением не считается (``route_matcher``), и удалять
    его — не уборка сирот: за архивирование отвечает человек.
    """
    fx = await _setup_minimal_route(session, sku="RD-ARCH", qty=Decimal("10"))
    archived_id = await _make_orphan_route(
        session, name="RD-archived", code=_auto_code("ARCH"), section_id=fx["prod"].id
    )
    await session.execute(
        update(ProductionRoute).where(ProductionRoute.id == archived_id).values(is_active=False)
    )
    await session.commit()

    assert archived_id not in {o.id for o in await find_orphan_routes(session)}

    report = await cleanup_orphan_routes(session, execute=True)

    assert archived_id not in report.deleted_ids
    assert await _count(
        session, select(func.count()).select_from(ProductionRoute).where(ProductionRoute.id == archived_id)
    ) == 1
