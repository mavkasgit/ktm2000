"""Каскадное удаление маршрута и критерий «маршрут-сирота» (#228).

Маршрут не удаляется одной строкой: на него ссылаются позиции плана,
строки плана участков, задания и позиции выпуска, а на его этапы —
ещё и внутренние планы. Порядок сноса задан внешними ключами, а не
порядком таблиц в коде: сначала дети, потом родитель.

Правила сноса ссылок:

* ``NOT NULL``-FK без ``ondelete`` — строка удаляется (иначе БД откажет);
  nullable-FK обнуляются, чтобы история цеха пережила удаление маршрута
  (брак, складской ledger, расхождения);
* ``daily_plan_items.work_task_id`` объявлен с ``ondelete=CASCADE`` —
  задания удаляются вместе со строками дневного плана, руками ничего
  трогать не нужно;
* объём сноса считается по реальным строкам, а не «на глаз»: функции
  :func:`count_route_relations` и :func:`delete_route_with_relations`
  читают один и тот же набор связей, поэтому предупреждение ручки
  удаления не может разойтись с тем, что она удалит.

Маршрут-сирота — маршрут, который импорт создал под новое состава, но
который ни одна позиция плана так и не выбрала: у него нет ни позиций,
ни строк плана участков, ни заданий, ни позиций выпуска. Такой маршрут
виден в подборе (`app/services/route_selection.py`) и только мешает.
Уборка — `scripts/cleanup_orphan_routes.py`, dry-run по умолчанию.

«Создал импорт» — тоже часть критерия, а не деталь: справочный код
(`universal_rp`, `dynamic_*`) у сид-маршрутов есть, и на свежей БД после
`db:seed` у них нет ни позиций, ни заданий. Без этого признака уборка
снесла бы эталонные маршруты завода, а `run_seed` их не восстановит.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect, TransferDiscrepancyDefectItem
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import (
    PlanChangeItem,
    PlanPosition,
    PositionStatusHistory,
)
from app.models.release_batch import ReleaseBatchPosition
from app.models.rework_task import ReworkTask
from app.models.route import (
    ProductionRoute,
    RouteMatchingRule,
    RouteOperation,
    RouteRuleCondition,
    RouteStage,
)
from app.models.transfer import Transfer, TransferDiscrepancy
from app.models.work_task import WorkTask
from app.stock.models import StockTransaction
from app.services.route_signature import AUTO_CODE_PREFIX


@dataclass(frozen=True)
class RouteRelations:
    """Сколько строк каждого вида связей держит маршрут."""

    stages: int
    operations: int
    matching_rules: int
    section_plan_lines: int
    work_tasks: int
    release_batch_positions: int
    plan_positions: int

    def warning_parts(self) -> list[str]:
        """Человекочитаемый список того, что уйдёт вместе с маршрутом."""
        parts: list[str] = []
        if self.stages:
            parts.append(f"{self.stages} шаг(ов) маршрута")
        if self.matching_rules:
            parts.append(f"{self.matching_rules} правило(ок) привязки")
        if self.section_plan_lines:
            parts.append(f"{self.section_plan_lines} линия(ий) плана участков")
        if self.work_tasks:
            parts.append(f"{self.work_tasks} задание(ий)")
        if self.release_batch_positions:
            parts.append(f"{self.release_batch_positions} позиция(ий) выпуска")
        if self.plan_positions:
            parts.append(f"{self.plan_positions} позиция(ий) плана")
        return parts

    @property
    def has_relations(self) -> bool:
        return bool(self.warning_parts())

    def as_counts_payload(self) -> dict[str, int]:
        """Счётчики для ``GET /routes/{id}/delete-check``."""
        return {
            "steps_count": self.stages,
            "rules_count": self.matching_rules,
            "spl_count": self.section_plan_lines,
            "work_tasks_count": self.work_tasks,
            "rbp_count": self.release_batch_positions,
            "plan_positions_count": self.plan_positions,
        }


async def _scalar_count(db: AsyncSession, entity, *whereclause) -> int:
    stmt = select(func.count()).select_from(entity)
    if whereclause:
        stmt = stmt.where(*whereclause)
    return int(await db.scalar(stmt) or 0)


async def _task_ids(db: AsyncSession, stage_ids: list[int], line_ids: list[int]) -> list[int]:
    """Задания маршрута: и по этапу, и по строке плана участков.

    Задание ссылается на оба ключа, и они могут разойтись (задание,
    созданное участком, привязано к строке плана с другим маршрутом).
    """
    clauses = []
    if stage_ids:
        clauses.append(WorkTask.route_stage_id.in_(stage_ids))
    if line_ids:
        clauses.append(WorkTask.section_plan_line_id.in_(line_ids))
    if not clauses:
        return []
    return list((await db.scalars(select(WorkTask.id).where(or_(*clauses)))).all())


async def count_route_relations(db: AsyncSession, route_id: int) -> RouteRelations:
    """Посчитать все связи маршрута — источник истины для 409 и для сноса."""
    stage_ids = list((await db.scalars(select(RouteStage.id).where(RouteStage.route_id == route_id))).all())
    line_ids = list(
        (await db.scalars(select(SectionPlanLine.id).where(SectionPlanLine.route_id == route_id))).all()
    )
    task_ids = await _task_ids(db, stage_ids, line_ids)
    return RouteRelations(
        stages=len(stage_ids),
        operations=await _scalar_count(
            db, RouteOperation, RouteOperation.route_stage_id.in_(stage_ids)
        ) if stage_ids else 0,
        matching_rules=await _scalar_count(
            db, RouteMatchingRule, RouteMatchingRule.route_id == route_id
        ),
        section_plan_lines=len(line_ids),
        work_tasks=len(task_ids),
        release_batch_positions=await _scalar_count(
            db, ReleaseBatchPosition, ReleaseBatchPosition.route_id == route_id
        ),
        plan_positions=await _scalar_count(db, PlanPosition, PlanPosition.route_id == route_id),
    )


async def _delete_task_dependents(db: AsyncSession, task_ids: list[int]) -> None:
    """Снос цеховых связей задания.

    ``NOT NULL``-FK (перемещения, задания на доработку) удаляются,
    nullable-FK (брак, складской ledger) обнуляются: факт брака —
    факт, и он не должен исчезать вместе с маршрутом.
    """
    if not task_ids:
        return

    transfer_ids = list(
        (
            await db.scalars(
                select(Transfer.id).where(
                    or_(
                        Transfer.from_task_id.in_(task_ids),
                        Transfer.to_task_id.in_(task_ids),
                    )
                )
            )
        ).all()
    )
    if transfer_ids:
        discrepancy_ids = list(
            (
                await db.scalars(
                    select(TransferDiscrepancy.id).where(
                        TransferDiscrepancy.transfer_id.in_(transfer_ids)
                    )
                )
            ).all()
        )
        if discrepancy_ids:
            await db.execute(
                delete(TransferDiscrepancyDefectItem).where(
                    TransferDiscrepancyDefectItem.transfer_discrepancy_id.in_(discrepancy_ids)
                )
            )
            await db.execute(
                delete(TransferDiscrepancy).where(TransferDiscrepancy.id.in_(discrepancy_ids))
            )
        await db.execute(
            update(StockTransaction)
            .where(StockTransaction.transfer_id.in_(transfer_ids))
            .values(transfer_id=None)
        )
        await db.execute(delete(Transfer).where(Transfer.id.in_(transfer_ids)))

    await db.execute(delete(ReworkTask).where(ReworkTask.source_task_id.in_(task_ids)))
    await db.execute(
        update(Defect).where(Defect.task_id.in_(task_ids)).values(task_id=None)
    )
    await db.execute(
        update(StockTransaction)
        .where(StockTransaction.task_id.in_(task_ids))
        .values(task_id=None)
    )


async def _delete_empty_internal_plans(db: AsyncSession, internal_plan_ids: list[int]) -> None:
    """Убрать внутренние планы, из которых не осталось ни одной строки.

    На ``internal_plans`` ссылается только ``section_plan_lines``, а эти
    строки уходят раньше. Внутренний план переживает удаление, только
    если у него остались строки чужого маршрута; план без строк — осколок
    выпуска, и его снос уже не блокируется внешними ключами.
    """
    if not internal_plan_ids:
        return
    still_used = set(
        (
            await db.scalars(
                select(SectionPlanLine.internal_plan_id).where(
                    SectionPlanLine.internal_plan_id.in_(internal_plan_ids)
                )
            )
        ).all()
    )
    empty_ids = [i for i in internal_plan_ids if i not in still_used]
    if not empty_ids:
        return
    await db.execute(delete(InternalPlan).where(InternalPlan.id.in_(empty_ids)))


async def delete_route_with_relations(
    db: AsyncSession,
    route: ProductionRoute,
    relations: RouteRelations | None = None,
) -> RouteRelations:
    """Удалить маршрут вместе со всеми связанными строками.

    ``relations`` — уже посчитанный :func:`count_route_relations`: вызывающий
    всё равно считает связи ради ответа 409, пересчитывать их здесь был бы
    лишний обход БД. Коммит делает вызывающий: сервис только сносит строки,
    чтобы откат остался за его транзакцией.
    """
    route_id = route.id

    stage_ids = list((await db.scalars(select(RouteStage.id).where(RouteStage.route_id == route_id))).all())
    line_ids = list(
        (await db.scalars(select(SectionPlanLine.id).where(SectionPlanLine.route_id == route_id))).all()
    )
    internal_plan_ids = list(
        (
            await db.scalars(
                select(SectionPlanLine.internal_plan_id)
                .where(SectionPlanLine.route_id == route_id)
                .distinct()
            )
        ).all()
    )
    position_ids = list(
        (await db.scalars(select(PlanPosition.id).where(PlanPosition.route_id == route_id))).all()
    )
    task_ids = await _task_ids(db, stage_ids, line_ids)

    relations = relations or await count_route_relations(db, route_id)

    # 1. Цеховые связи заданий — до самих заданий.
    await _delete_task_dependents(db, task_ids)

    # 2. Задания, затем строки плана участков (work_tasks.section_plan_line_id
    #    — NOT NULL FK, строки обязаны уйти раньше).
    if task_ids:
        await db.execute(delete(WorkTask).where(WorkTask.id.in_(task_ids)))
    if line_ids:
        await db.execute(
            update(StockTransaction)
            .where(StockTransaction.section_plan_line_id.in_(line_ids))
            .values(section_plan_line_id=None)
        )
        await db.execute(delete(SectionPlanLine).where(SectionPlanLine.id.in_(line_ids)))
    await _delete_empty_internal_plans(db, internal_plan_ids)

    # 3. Позиции выпуска — раньше позиций плана (NOT NULL FK plan_position_id).
    if relations.release_batch_positions:
        await db.execute(
            delete(ReleaseBatchPosition).where(ReleaseBatchPosition.route_id == route_id)
        )

    # 4. Позиции плана со своей историей статусов.
    if position_ids:
        await db.execute(
            delete(PlanChangeItem).where(PlanChangeItem.plan_position_id.in_(position_ids))
        )
        await db.execute(
            delete(PositionStatusHistory).where(
                PositionStatusHistory.plan_position_id.in_(position_ids)
            )
        )
        await db.execute(delete(PlanPosition).where(PlanPosition.id.in_(position_ids)))

    # 5. Операции этапов — ORM-каскад при bulk-удалении этапов не
    #    срабатывает, поэтому операции сносятся явно.
    if stage_ids:
        await db.execute(
            delete(RouteOperation).where(RouteOperation.route_stage_id.in_(stage_ids))
        )

    # 6. Правила привязки вместе со своими условиями.
    rule_ids = list(
        (await db.scalars(select(RouteMatchingRule.id).where(RouteMatchingRule.route_id == route_id))).all()
    )
    if rule_ids:
        await db.execute(
            delete(RouteRuleCondition).where(RouteRuleCondition.rule_id.in_(rule_ids))
        )
        await db.execute(delete(RouteMatchingRule).where(RouteMatchingRule.id.in_(rule_ids)))

    if stage_ids:
        await db.execute(delete(RouteStage).where(RouteStage.id.in_(stage_ids)))

    # Коллекции могли прийти из БД до bulk-удаления — сбрасываем, чтобы
    # ORM не пытался донести до БД уже удалённые строки.
    db.expire(route, ["stages", "rules"])
    await db.delete(route)
    return relations


@dataclass(frozen=True)
class OrphanRoute:
    """Маршрут-сирота: импорт создал, но ни одна позиция его не взяла."""

    id: int
    code: str | None
    name: str
    stages: int

    def render(self) -> str:
        code = self.code or "—"
        return f"  #{self.id} [{code}] {self.name} (этапов: {self.stages})"


@dataclass
class OrphanCleanupReport:
    """Итог уборки: что нашли и что удалили (при ``execute``)."""

    found: list[OrphanRoute] = field(default_factory=list)
    deleted_ids: list[int] = field(default_factory=list)
    executed: bool = False


async def find_orphan_routes(db: AsyncSession) -> list[OrphanRoute]:
    """Маршруты, которые создал импорт и ни одна позиция не взяла.

    Критерий сироты (тикет #228), два условия ОБЯЗАТЕЛЬНЫ:

    * маршрут создал импорт — у него нет справочного кода: код ``NULL``
      (маршрут, созданный импортом до #230) либо ``auto-<хеш>``
      (детерминированный код из сигнатуры, ADR-0051). Сид-маршруты завода
      ``universal_rp`` и ``dynamic_*`` несут справочный код, и на свежей
      БД после ``db:seed`` у них нет ни позиций, ни заданий — то есть
      по одному лишь признаку «нет связей» уборка снесла бы эталонные
      маршруты, а ``run_seed`` их не восстановит: он ищет существующие
      строки по коду и только их обновляет;
    * маршрут не архивный (``is_active``) — архивный маршрут назначением
      не считается (``route_matcher``), и убирать его уборке сирот нечего.

    Плюс прежний признак #228: ни позиций плана, ни строк плана участков,
    ни заданий на этапах маршрута, ни позиций выпуска. Этапы, операции и
    правила привязки — не данные, они уходят каскадом. Маршруты с любыми
    из этих строк уборка не трогает.
    """
    rows = (
        await db.execute(
            select(ProductionRoute.id, ProductionRoute.code, ProductionRoute.name)
            .where(
                # Справочный код — признак «маршрут создал не импорт».
                # Фильтр в выборке, а не после неё: иначе эталонные
                # сид-маршруты попали бы в отчёт dry-run.
                ProductionRoute.is_active.is_(True),
                or_(
                    ProductionRoute.code.is_(None),
                    ProductionRoute.code.like(f"{AUTO_CODE_PREFIX}%"),
                ),
                ~select(PlanPosition.id)
                .where(PlanPosition.route_id == ProductionRoute.id)
                .exists()
                .correlate(ProductionRoute),
                ~select(SectionPlanLine.id)
                .where(SectionPlanLine.route_id == ProductionRoute.id)
                .exists()
                .correlate(ProductionRoute),
                ~select(ReleaseBatchPosition.id)
                .where(ReleaseBatchPosition.route_id == ProductionRoute.id)
                .exists()
                .correlate(ProductionRoute),
                ~select(WorkTask.id)
                .select_from(WorkTask)
                .join(RouteStage, WorkTask.route_stage_id == RouteStage.id)
                .where(RouteStage.route_id == ProductionRoute.id)
                .exists()
                .correlate(ProductionRoute),
            )
            .order_by(ProductionRoute.id)
        )
    ).all()
    if not rows:
        return []
    ids = [row.id for row in rows]
    stages_by_route = dict(
        (
            await db.execute(
                select(RouteStage.route_id, func.count(RouteStage.id))
                .where(RouteStage.route_id.in_(ids))
                .group_by(RouteStage.route_id)
            )
        ).all()
    )
    return [
        OrphanRoute(
            id=row.id,
            code=row.code,
            name=row.name,
            stages=int(stages_by_route.get(row.id, 0)),
        )
        for row in rows
    ]


async def cleanup_orphan_routes(
    db: AsyncSession, *, execute: bool = False
) -> OrphanCleanupReport:
    """Найти (и по ``execute`` — удалить) маршруты-сироты.

    По умолчанию только читает: показ списка перед удалением обязателен,
    маршрут с позицией или историей цеха уборка не трогает в любом
    режиме. Коммит — только при ``execute`` и только своих строк.
    """
    orphans = await find_orphan_routes(db)
    report = OrphanCleanupReport(found=orphans, executed=execute)
    if not execute:
        return report

    for orphan in orphans:
        route = await db.get(ProductionRoute, orphan.id)
        if route is None:
            continue
        await delete_route_with_relations(db, route)
        report.deleted_ids.append(orphan.id)
    await db.commit()
    return report
