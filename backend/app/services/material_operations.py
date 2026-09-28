"""Пройденные операции материала (ADR-0043, тикет #207).

Признак «какие операции материал уже прошёл» нужен, чтобы отличить
подготовленное сырьё на «Складе подготовки» от сырья на «Складе сырья»:
по ``stock_balances`` это неразличимо, а по маршруту — однозначно.

Источник правды — **маршрут позиции**: признак проводки есть объединение
``section_operations.operation_code`` всех секций этапов маршрута с
``sequence <=`` заданного. Для маршрута №3 (ЮП-460) это даёт ровно то,
что описано в тикете::

    этап 1 «Склад сырья»        → ISSUE_RAW
    этап 2 «Пресс»              → PRESS_COMB, PRESS_WINDOW
    этап 3 «Дробеструй»         → SHOT
    этап 4 «Склад подготовки»   → ISSUE_RAW, PRESS_COMB, PRESS_WINDOW,
                                   SHOT, MOVE_TO_PREP_STOCK

Атрибуция не угадывается (ADR-0021): материал на складе может быть
смешанным, но маршрут позиции известен точно, и признак выводится из
него, а не реконструируется обратным чтением ledger.

Форма хранения (канонизация, зеркало компенсаций) проверяется в
``StockCommandService.record()`` — единственном пути записи в ledger.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteStage
from app.models.work_task import WorkTask


class CompletedOperationsError(ValueError):
    """Некорректный список пройденных операций (форма или справочник)."""


def canonicalize_completed_operations(
    values: Iterable[str] | None,
) -> list[str] | None:
    """Каноническая форма признака: отсортированный список без дублей.

    ``None`` — состояние не зафиксировано (операция вне маршрута) и
    остаётся ``None``. Пустой список — осмысленное значение: «материал
    прошёл маршрут, операций не было»; он НЕ схлопывается в ``None``.

    Ровно тот же приём, что с ``dimensions`` (ADR-0001): ledger хранит
    только каноническую форму, иначе два эквивалентных представления
    одного признака разъезжаются при сравнении и зеркалировании.
    """
    if values is None:
        return None
    codes: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise CompletedOperationsError(
                f"completed_operations must be a list of operation_code strings, "
                f"got element of type {type(raw).__name__}"
            )
        code = raw.strip()
        if not code:
            raise CompletedOperationsError(
                "completed_operations must not contain empty operation_code"
            )
        codes.add(code)
    return sorted(codes)


async def assert_known_operation_codes(
    db: AsyncSession, codes: list[str]
) -> None:
    """Все коды признака обязаны существовать в справочнике операций секций.

    Иначе в ledger попадёт опечатка, и признак невозможно будет сопоставить
    с реальностью процесса.
    """
    if not codes:
        return
    from app.models.route import SectionOperation

    known = set(
        (
            await db.execute(
                select(SectionOperation.operation_code).where(
                    SectionOperation.operation_code.in_(codes)
                )
            )
        )
        .scalars()
        .all()
    )
    unknown = sorted(set(codes) - known)
    if unknown:
        raise CompletedOperationsError(
            f"unknown operation_code(s) in completed_operations: {unknown}"
        )


async def completed_operations_through_stage(
    db: AsyncSession,
    *,
    route_id: int,
    through_sequence: int,
) -> list[str]:
    """Операции всех этапов маршрута с ``sequence <= through_sequence``.

    Транзитные (складские) этапы не выбрасываются: их операции —
    ``ISSUE_RAW``/``MOVE_TO_PREP_STOCK`` — часть фактической истории
    материала и именно они отличают «Сырьё» от «Подготовлено».
    """
    if route_id is None or through_sequence is None:
        return []
    from app.models.route import SectionOperation

    codes = (
        await db.execute(
            select(SectionOperation.operation_code)
            .join(RouteStage, RouteStage.section_id == SectionOperation.section_id)
            .where(
                RouteStage.route_id == route_id,
                RouteStage.sequence <= through_sequence,
                SectionOperation.operation_code.isnot(None),
            )
            .distinct()
        )
    ).scalars().all()
    return sorted({code for code in codes if code})


async def completed_operations_for_task(
    db: AsyncSession,
    task: WorkTask,
    *,
    through_sequence: int | None = None,
) -> list[str] | None:
    """Признак для материала, который двигается по проводке задания.

    ``through_sequence`` — до какого этапа маршрута материал прошёл;
    по умолчанию это собственный этап задания. Случаи «вход до текущего
    этапа» (трансформирующий этап ADR-0002) и «возврат на предыдущий
    этап» (дефект) передают его явно.

    ``None`` — задание не привязано к строке плана: состояние не
    определяется, признак остаётся неизвестным (а не пустым).
    """
    from app.models.internal_plan import SectionPlanLine

    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is None:
        return None
    sequence = through_sequence
    if sequence is None:
        stage = await db.get(RouteStage, task.route_stage_id)
        if stage is None:
            return None
        sequence = stage.sequence
    return await completed_operations_through_stage(
        db, route_id=line.route_id, through_sequence=sequence
    )


async def previous_stage_sequence(
    db: AsyncSession, task: WorkTask
) -> int | None:
    """``sequence`` предыдущего этапа маршрута задания (или ``None``)."""
    from app.models.internal_plan import SectionPlanLine

    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    stage = await db.get(RouteStage, task.route_stage_id)
    if line is None or stage is None:
        return None
    previous = await db.scalar(
        select(RouteStage.sequence)
        .where(
            RouteStage.route_id == line.route_id,
            RouteStage.sequence < stage.sequence,
        )
        .order_by(RouteStage.sequence.desc())
        .limit(1)
    )
    return previous
