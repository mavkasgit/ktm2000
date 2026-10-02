"""Переиспользуемая цепочка сборки состояния для тестов передач (#304, #300).

Зачем
----
Два тикета упирались в одну и ту же недостающую фикстуру и строили её дважды:

* **#304** — released-план-строка **складского** участка **без** ``WorkTask``:
  только такой строке ``GET /transfers/ready`` вынужден создавать задание
  лениво (внутри GET), и без него поведение нечем измерять — на живых данных
  у всех строк выдачи задание уже есть;
* **#300** — ``MANUAL_IN`` на склад сырья → ``transfer_send`` на участок →
  задание на доске → ``complete_task(auto_transfer_next=True)``, который
  порождает авто-передачу.

Ключевой момент, из-за которого оба раза упирались в сборочный код: **выпуск
плана создаёт ``SectionPlanLine`` на каждый этап маршрута, но задание — только
на производственных** (``plan_generation.release_batch``, «WorkTask создаётся
только при ``is_production_section``»). Поэтому складская released-строка без
задания получается сама собой, если выпустить настоящий план, а не склеить
строки руками. Эта фикстура идёт именно этим путём — как в бою.

Подписи операций
----------------
Ось ``completed_operations`` в бюджете (ADR-0017/0018) — ловушка фикстур:
``MANUAL_IN``, засеянный с другой подписью, чем у плановой отправки, даёт
строке нулевой бюджет, и строка молча не попадает в выдачу. Поэтому приём
всегда идёт через резолверы ``app.services.material_operations``, а не через
 литерал в тесте.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import PlanPositionStatus
from app.services.route_storage_classifier import (
    SECTION_TYPE_FINISHED_STOCK,
    SECTION_TYPE_RAW_STOCK,
    SECTION_TYPE_WIP_STOCK,
)
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_generation import create_release_batch, release_batch
from app.stock.models import Reason, QualityState
from app.stock.services import StockCommand, StockCommandService

from tests.helpers.completed_operations import build_operation_route

#: Коды операций этапов. Имена должны быть уникальными на скиму: `SectionOperation`
#: уникален по (section_id, operation_code), а бюджет считает по подписи целиком.
ISSUE_RAW_OP = "ISSUE_RAW"
WIP_CONSUME_OP = "WIP_CONSUME"
WIP_ISSUE_OP = "WIP_ISSUE"
PROD_START_OP = "PROD_START"


async def build_released_stock_lines(
    session: AsyncSession,
    *,
    sku: str,
    qty: Decimal = Decimal(50),
) -> dict:
    """Маршрут «склад → склад» с выпущенными позициями и НЕзаданными строками.

    Обе секции — складские (``raw_stock`` → ``wip_stock``), поэтому выпуск
    плана не создаёт на них заданий вовсе: строки выходят в выдачу
    ``/transfers/ready`` только через ленивое создание (#304).

    Одна позиция — одна строка выдачи без задания. Чтобы получить N строк,
    кейс строят N раз с разными ``sku`` и запрашивают выдачу без фильтра по
    участку: это и есть ключ к замеру «сколько стоит поштучный путь на N».

    Возвращает ``{user, product, plan, positions, sections, route_stages,
    lines, ops_by_stage}``.
    """
    fixture = await build_operation_route(
        session,
        sku=sku,
        qty=qty,
        stages=[
            (f"{sku}-RAW", SECTION_TYPE_RAW_STOCK, [ISSUE_RAW_OP]),
            (f"{sku}-WIP", SECTION_TYPE_WIP_STOCK, [WIP_CONSUME_OP]),
        ],
        with_plan_lines=False,
    )

    await session.refresh(fixture["position"])
    plan = fixture["plan"]
    released = await create_release_batch(session, production_plan_id=plan.id, positions=None)
    await release_batch(session, released["id"])
    released_positions = [fixture["position"]]

    # Строки выпущенного плана достаём из БД: build_operation_route их не
    # создавал (with_plan_lines=False), а release_batch — создал.
    from app.models.internal_plan import SectionPlanLine

    db_lines = list(
        (
            await session.execute(
                select(SectionPlanLine).where(
                    SectionPlanLine.plan_position_id.in_([p.id for p in released_positions])
                )
            )
        )
        .scalars()
        .all()
    )

    ops_by_stage: dict[int, list[str]] = {}
    for stage in fixture["route_stages"]:
        ops_by_stage[stage.sequence] = await completed_operations_through_stage(
            session, route_id=fixture["route"].id, through_sequence=stage.sequence
        )

    fixture.update(
        {
            "release_batch_id": released["id"],
            "positions_released": released_positions,
            "lines": db_lines,
            "ops_by_stage": ops_by_stage,
        }
    )
    return fixture


async def seed_manual_in(
    session: AsyncSession,
    *,
    user_id: int,
    location_id: int,
    product_id: int,
    quantity: Decimal,
    completed_operations: list[str],
) -> None:
    """``MANUAL_IN`` с подписью операций, как её ждёт бюджет.

    Обёртка над ``StockCommandService.record``: приём остатков в ledger — один
    законный путь, и тесты не должны собирать ``StockTransaction`` руками.
    """
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product_id,
            quantity=quantity,
            reason=Reason.MANUAL_IN,
            to_location_id=location_id,
            quality_state=QualityState.GOOD,
            created_by=user_id,
            completed_operations=completed_operations,
        ),
    )
    await session.commit()


__all__ = [
    "ISSUE_RAW_OP",
    "PROD_START_OP",
    "SECTION_TYPE_FINISHED_STOCK",
    "SECTION_TYPE_PRODUCTION",
    "WIP_CONSUME_OP",
    "WIP_ISSUE_OP",
    "build_released_stock_lines",
    "seed_manual_in",
]