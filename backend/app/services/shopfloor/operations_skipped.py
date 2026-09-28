"""Пропуск этапа позиции (тикет #207, решение Q6).

Материал может быть подан на маршрут уже готовым: «Склад подготовки»
передаёт заготовку сразу на Анодирование, и этапы Пресс и Дробеструй
физически не выполняются. Раньше такой позиции нельзя было закрыть —
пропуск неотличим от «ещё не сделано», и предыдущие этапы навсегда
оставались незакрытыми.

Поэтому пропуск — явное состояние, а не отсутствие работы:

* этап получает ``WorkTaskStatus.skipped`` **с причиной** («материал подан
  в готовом виде»), и он закрывает позицию наравне с выполненным;
* **никаких проводок ledger не создаётся** — по skipped-этапу материала
  нет и никогда не было, писать движение значило бы выдумать его;
* этап нельзя пропустить, если он уже выполнен или отменён: пропуск —
  не отмена и не переделка.

Альтернатива «начать позицию с этапа 5, предыдущие не трогать» была
отклонена на гриллинге: позиция навсегда осталась бы с незакрытыми
предыдущими этапами, а «задача закрыта = все этапы закрыты» — инвариант
прогресса, отчётности и отмены.

Пропуск ставит выдача из подготовленного материала (#207, отдельный
тикет на автоподбор источника); здесь — единственный путь записи
состояния и всё, что из него следует в прогрессе и отчётности.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.cache import _refresh_section_plan_line_cache

# Причина по умолчанию: материал уже готов, этап не выполнялся.
SKIP_REASON_MATERIAL_READY = "Материал подан в готовом виде"


async def skip_stage(
    db: AsyncSession,
    *,
    section_plan_line_id: int,
    reason: str = SKIP_REASON_MATERIAL_READY,
) -> WorkTask:
    """Пометить этап позиции пропущенным и вернуть его задание.

    Задание создаётся, если его ещё нет: пропущенный этап обязан быть
    виден в прогрессе позиции, а не отсутствовать в нём.

    Проводок ledger не создаётся — по skipped-этапу материала нет.
    """
    line = await db.get(SectionPlanLine, section_plan_line_id)
    if line is None:
        raise ValueError(f"SectionPlanLine {section_plan_line_id} not found")
    if not reason or not reason.strip():
        raise ValueError("Пропуск этапа требует причины")

    task = await db.scalar(
        select(WorkTask)
        .where(WorkTask.section_plan_line_id == line.id)
        .order_by(WorkTask.id.asc())
        .limit(1)
    )
    if task is None:
        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=line.section_id,
            product_id=line.product_id,
            route_stage_id=line.route_stage_id,
            planned_quantity=line.planned_quantity,
            status=WorkTaskStatus.skipped,
            skip_reason=reason.strip(),
        )
        db.add(task)
    else:
        if task.status == WorkTaskStatus.completed:
            raise ValueError(
                "Выполненный этап нельзя пропустить — он уже закрыт работой"
            )
        if task.status == WorkTaskStatus.cancelled:
            raise ValueError(
                "Отменённый этап нельзя пропустить — отмена не переигрывается"
            )
        task.status = WorkTaskStatus.skipped
        task.skip_reason = reason.strip()

    await db.flush()
    await _refresh_section_plan_line_cache(db, line.id)
    return task
