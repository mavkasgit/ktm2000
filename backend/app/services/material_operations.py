"""Пройденные операции материала (ADR-0043, ADR-0061, тикеты #207, #272).

Признак «какие операции материал уже прошёл» нужен, чтобы отличить
подготовленное сырьё на «Складе подготовки» от сырья на «Складе сырья»:
по ``stock_balances`` это неразличимо, а по маршруту — однозначно.

Источник правды — **операции этапов маршрута позиции**: признак проводки
есть объединение ``route_operations.operation_code`` этапов с
``sequence <=`` заданного (ADR-0061; до него брался справочник участка
целиком, и один остаток нёс операции, которых не проходил). Для маршрута,
где пила режет 2,7 м на 1,8 м, признак на выходе пилы — ровно ``SAW_1800``,
а не все длины раскроя участка.

Транзитные (складские) этапы операций не несут и в признак ничего не
добавляют: их ``resolver_type``/``ISSUE_RAW``-подобные записи участка —
не работа с материалом.

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


# Подписи двух пустых состояний оси операций (ADR-0055 п.6). Это НЕ имена
# операций, а то, что видит оператор в колонке «Операции»: у строки без
# признака имён просто нет, поэтому обычное сравнение по названиям их не
# различило бы. Один источник строк на весь бэкенд — иначе фильтр колонки,
# подпись в ответе и подпись в сводке разъехались бы текстом.
OPERATIONS_NOT_RECORDED_LABEL = "не зафиксировано"
OPERATIONS_EMPTY_LABEL = "без операций"


def completed_operation_stages(
    ops: list[str] | None, operations: list[dict]
) -> list[dict]:
    """Этапы справочника, соответствующие кодам признака, — в порядке справочника.

    ``operations`` — справочник в формате ``resolve_operations_dictionary``
    (``RouteStepsDisplay``), уже упорядоченный по ``(section.sort_order,
    section.id, section_operation.sort_order, section_operation.id)``. Результат —
    та же последовательность, срезанная по кодам признака: порядок не
    вычисляется заново, а наследуется из позиции этапа в справочнике.

    Фактический порядок именно такой, а не «по ``sequence``»: ``sequence`` — это
    только ``section.sort_order``, а обход идёт по массиву кодов ``ops``, в
    канонической форме отсортированному алфавитно по коду
    (``canonicalize_completed_operations``). Устойчивый ``sorted`` по одному
    ``sequence`` внутри секции сохранил бы этот алфавит, и подпись ячейки
    разошлась бы с SQL-подписью колонки «Операции»
    (``stock/api.py::_balance_operations_label_expr``, где в ``ORDER BY`` идёт
    ``(section.sort_order, section.id, operation.sort_order, operation.id)``):
    фильтр по значению ячейки искал бы другой порядок имён и молча возвращал
    ноль строк.

    Код, которого нет в справочнике, в набор этапов не попадает: ``record()``
    отвергает такие на записи, он мог остаться лишь от удаления справочной
    записи — молчаливое отбрасывание сделало бы строку неотличимой от
    «операций не было». Повтор кода в справочнике (уникальность — по паре
    ``section_id, operation_code``) разрешается в пользу последней записи,
    как и раньше, когда строился только словарь по кодам.
    """
    by_code: dict[str, dict] = {}
    position: dict[str, int] = {}
    for index, operation in enumerate(operations):
        code = operation["operation_code"]
        by_code[code] = operation
        position[code] = index
    return sorted(
        (
            by_code[code]
            for code in (ops or [])
            if code in by_code
        ),
        key=lambda stage: position[stage["operation_code"]],
    )


def format_completed_operations_label(
    ops: list[str] | None, stages: list[dict] | None = None
) -> str:
    """Человекочитаемая подпись оси операций — зеркало клиентской.

    Три различимых состояния (ADR-0055 п.6): ``None`` — «не зафиксировано»,
    ``[]`` — «без операций», список — имена пройденных операций. Имена берутся
    из ``stages`` (развёрнутый справочником признак); если справочник не
    разрешился, печатаются коды — иначе непустой признак выглядел бы как
    «без операций» и две разные группы остатка получили бы одну подпись.
    """
    if ops is None:
        return OPERATIONS_NOT_RECORDED_LABEL
    if not ops:
        return OPERATIONS_EMPTY_LABEL
    names = [
        stage["operation_name"]
        for stage in (stages or [])
        if stage.get("operation_name")
    ]
    return ", ".join(names) if names else ", ".join(ops)


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
    """Операции этапов маршрута с ``sequence <= through_sequence``.

    Источник — операции САМОГО этапа (``route_operations``), а не справочник
    участка (ADR-0061): материал проходил конкретную операцию своего этапа
    (цвет анодирования, длину раскроя, вид упаковки), и объединение операций
    участка приписало бы ему состояния, которых не было — у баланса 2,7 м
    появлялись бы «реза на 0,9/1,35/1,8 м», у чёрного профиля — все цвета.

    Транзитные (складские) этапы операций не несут и в признак ничего не
    добавляют; этап, не назвавший операцию (``operation_code IS NULL`` —
    заглушка шаблонного маршрута), — тоже.
    """
    if route_id is None or through_sequence is None:
        return []
    from app.models.route import RouteOperation

    codes = (
        await db.execute(
            select(RouteOperation.operation_code)
            .join(RouteStage, RouteStage.id == RouteOperation.route_stage_id)
            .where(
                RouteStage.route_id == route_id,
                RouteStage.sequence <= through_sequence,
                RouteOperation.operation_code.isnot(None),
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
