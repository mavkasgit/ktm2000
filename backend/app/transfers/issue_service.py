"""Исполнение выдачи с автоподбором источника (#282).

Модель: **одна выдача = N передач** (по одной на склад-источник). Каждая
передача — живой ``Transfer`` со своим ``transfer_no``, своей записью
``Action`` (``action_type="transfer_send"``), своей идемпотентностью и своей
отменой; группа связана одним ``issue_no`` (#282, решение 1 гриллинга —
родительского узла ``Action`` в первой версии нет).

Почему не ``transfer_send``: у него источник — ЗАДАНИЕ (``from_task_id``),
а лимит считается по ``task_transferable``, который выводит признак операций
из маршрута задания-источника (``transfers/transferable.py``). Склад-источник
выдачи — строка ``StockBalance`` с её собственным признаком операций, и
задание-источник на неё не заводишь: fake-task склада не знает ни размер, ни
ops-ось, а «передавать» пришлось бы через лимит плана строки. Поэтому здесь
``Transfer`` + ``Action`` + пара проводок пишутся напрямую — ровно та же
форма, что у выдачи оператора в ``services/plan_generation.py``
(``take_to_work_source``), но с ``transfer_id``/``action_id`` на обеих
проводках: ``sent_quantity`` сверяется ledger-инвариантом S6, а 1:1
``TRANSFER_SEND``/``TRANSFER_RECEIVE`` по одному ``action_id`` — инвариант
журнала (ADR-0019).

Что делает ``execute_issue``:

1. **блокирует FOR UPDATE все строки баланса группы эквивалентов на
   складах** (ключ ``группа × склад`` — шире, чем любой возможный план
   подбора; ADR-0073) и только после этого подбирает план ровно один раз —
   иначе две одновременные выдачи на разные SKU одной группы вычерпали бы
   одну кучу дважды, а предвыборка-пересчёт в той же сессии вернула бы
   устаревшие copies из identity map;
2. пишет N передач в одной сессии: непредвиденная техническая ошибка на
   середине откатывает операцию целиком, а «собрано меньше» — исход, а не
   ошибка (стратегии ``shortage_strategy``);
3. помечает прыгнутые этапы статусом ``skipped`` с ``skipped_by_issue_no``
   — своим номером выдачи, чтобы отмена сняла только свои пропуски.

``cancel_issue`` отменяет передачи по одной существующим
``cancel_transfer`` (свой ``transfer_send`` Action + ``ReversalService``) и
снимает пропуски, поставленные этим ``issue_no``.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import format_dimensions
from app.domain.shortage import ShortageStrategy
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition
from app.models.route import RouteStage
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import CLOSED_WORK_TASK_STATUSES, WorkTask, WorkTaskStatus
from app.services.action_journal_service import action_journal_service
from app.services.product_alias_groups import AliasGroupCache, load_alias_groups
from app.services.route_storage_classifier import SECTION_TYPE_PRODUCTION, STOCK_TYPES
from app.services.shopfloor.cache import _refresh_section_plan_line_cache
from app.services.shopfloor.common import (
    _check_idempotency,
    _get_user_snapshot_name,
    _transfer_no,
)
from app.services.shopfloor.operations_skipped import (
    SKIP_REASON_MATERIAL_READY,
    skip_stage,
)
from app.stock.models import Reason, StockBalance
from app.stock.services import (
    StockCommand,
    StockCommandService,
    dimensions_match_clause,
)
from app.transfers.source_selection import IssuePlan, build_issue_plan

__all__ = [
    "build_issue_preview_payload",
    "cancel_issue",
    "execute_issue",
    "issue_no_now",
    "preview_issue_cancellation",
]

ZERO = Decimal(0)
_stock_command_service = StockCommandService()


def issue_no_now() -> str:
    """Номер выдачи: одна метка на N передач (#282).

    Формат совпадает с ``_transfer_no`` (UTC ``%Y%m%d%H%M%S%f``) с префиксом
    ``ISS-`` — номер человекочитаемый, упорядоченный по времени и не
    конфликтует с номерами передач.
    """
    return "ISS-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


# ─── Предпросмотр для окна «Взять в работу» ─────────────────────────────────


def _fmt_qty(value: Decimal) -> str:
    """Число для UI без хвостов ``.000`` (3.000 → «3», 2.500 → «2,5»)."""
    normalized = Decimal(str(value)).normalize()
    if normalized == normalized.to_integral_value():
        return str(int(normalized))
    return format(normalized, "f").replace(".", ",")


async def build_issue_preview_payload(
    db: AsyncSession,
    *,
    position: PlanPosition,
    product_id: int,
    required: Decimal,
    excluded_balance_ids: set[int] | None = None,
) -> dict[str, Any]:
    """JSON предпросмотра подбора: список с галочками, порядок, итог, подсказки.

    Ответ сервера — единственный источник порядка и количеств: оператор не
    вводит их руками и не может добавить склад, который система не позвала
    (#282). Строки отсортированы по полю ``order``.

    Справочник групп читается один раз на запрос (``AliasGroupCache``) и
    передаётся в подбор готовым — второй SELECT групп на строку баланса не
    появляется.
    """
    cache = AliasGroupCache()
    alias_groups = await load_alias_groups(db, {product_id}, cache=cache)
    plan = await build_issue_plan(
        db,
        position=position,
        product_id=product_id,
        required=required,
        excluded_balance_ids=excluded_balance_ids or set(),
        alias_groups=alias_groups,
    )
    return serialize_issue_plan(plan)


def serialize_issue_plan(plan: IssuePlan) -> dict[str, Any]:
    candidates = sorted(plan.candidates, key=lambda c: c.order)
    return {
        "position_id": plan.position_id,
        "product_id": plan.product_id,
        "group_key": plan.group_key,
        "group_skus": list(plan.group_skus),
        "required": _fmt_qty(plan.required),
        "required_dimensions": plan.required_dimensions,
        "required_dimensions_label": (
            format_dimensions(plan.required_dimensions)
            if plan.required_dimensions is not None
            else None
        ),
        "collected": _fmt_qty(plan.collected),
        "deficit": _fmt_qty(plan.deficit),
        "candidates": [
            {
                "balance_id": c.balance_id,
                "location_id": c.location_id,
                "location_name": c.location_name,
                "group_key": c.group_key,
                "product_id": c.product_id,
                "sku": c.sku,
                "dimensions": c.dimensions,
                "completed_operations": c.completed_operations,
                "ops_count": c.ops_count,
                "available": _fmt_qty(c.available),
                "take": _fmt_qty(c.take),
                # None — прочерк («не доходила очередь» / «снята галочка»);
                # "0" — склад вычерпан целиком (#282: пустеющий склад
                # показывает 0, а не подпись).
                "remaining_after": None if c.remaining_after is None else _fmt_qty(c.remaining_after),
                "included": c.included,
                "target_sequence": c.target_sequence,
                "order": c.order,
            }
            for c in candidates
        ],
        "hints": [
            {
                "kind": h.kind,
                "location_id": h.location_id,
                "location_name": h.location_name,
                "quantity": _fmt_qty(h.quantity),
                "text": h.text,
            }
            for h in plan.hints
        ],
    }


# ─── Отказ на русском (без цифровых id склада и артикула) ──────────────────


def _shortage_reason(location_names: list[str], collected: Decimal, required: Decimal) -> str:
    """«нужно 60, на Хранилище Б осталось 12» — имена, а не id (#282)."""
    deficit = required - collected
    where = ", ".join(f"«{name}»" for name in location_names) if location_names else "доступных складов"
    return (
        f"Нужно {_fmt_qty(required)} шт., а на {where} осталось {_fmt_qty(collected)} шт. "
        f"— не хватает {_fmt_qty(deficit)} шт. Передавать нельзя: выдача отменена целиком."
    )


# ─── Исполнение выдачи ─────────────────────────────────────────────────────


async def _target_task_for_sequence(
    db: AsyncSession,
    *,
    position: PlanPosition,
    sequence: int,
    product_id: int,
    dimensions: dict | None,
    planned_qty: Decimal,
    actor_id: int,
) -> tuple[WorkTask, SectionPlanLine]:
    """Задание этапа-адресата для ``sequence`` (создаётся лениво, как в transfer_send)."""
    line = await db.scalar(
        select(SectionPlanLine).where(
            SectionPlanLine.plan_position_id == position.id,
            SectionPlanLine.sequence == sequence,
        )
    )
    if line is None:
        raise ValueError(
            "Источник выдачи: этап, который должен принять материал, ещё не создан "
            "— позицию нужно сначала взять в работу"
        )
    task = await db.scalar(
        select(WorkTask)
        .where(
            WorkTask.section_plan_line_id == line.id,
            WorkTask.status.notin_(CLOSED_WORK_TASK_STATUSES),
            dimensions_match_clause(WorkTask.dimensions, dimensions),
        )
        .order_by(WorkTask.id.asc())
    )
    if task is None:
        closed = await db.scalar(
            select(WorkTask)
            .where(
                WorkTask.section_plan_line_id == line.id,
                WorkTask.status.in_(CLOSED_WORK_TASK_STATUSES),
            )
            .order_by(WorkTask.id.asc())
        )
        if closed is not None and closed.status in {
            WorkTaskStatus.completed,
            WorkTaskStatus.skipped,
        }:
            raise ValueError(
                "Источник выдачи: этап уже закрыт работой или пропущен — "
                "выдавать на него материал нельзя"
            )
        from app.services.route_transform import transform_fields_for_task

        transform_fields = await transform_fields_for_task(
            db,
            route_stage_id=line.route_stage_id,
            plan_position_id=line.plan_position_id,
            task_quantity=planned_qty,
        )
        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=line.section_id,
            product_id=product_id,
            route_stage_id=line.route_stage_id,
            planned_quantity=planned_qty,
            status=WorkTaskStatus.waiting_previous,
            due_date=line.due_date,
            dimensions=dimensions,
            **transform_fields,
        )
        db.add(task)
        await db.flush()
    return task, line


async def _record_issue_transfer(
    db: AsyncSession,
    *,
    position: PlanPosition,
    product_id: int,
    issue_no: str,
    balance: StockBalance,
    quantity: Decimal,
    target_sequence: int,
    actor_id: int,
    idempotency_key: str,
    now: datetime,
    allow_negative: bool,
    source_sku: str | None = None,
) -> dict[str, Any]:
    """Одна передача выдачи: Transfer + Action + пара проводок ledger.

    Канонизация на границе выдачи (ADR-0073 п.5): ``TRANSFER_SEND`` несёт
    фактический SKU источника, ``TRANSFER_RECEIVE`` — артикул задания;
    ``Transfer`` и создаваемое задание живут под артикулом задания.
    """
    dimensions = balance.dimensions
    completed_ops = list(balance.completed_operations or [])
    quality = balance.quality_state
    source_product_id = balance.product_id
    target_product_id = product_id

    task, line = await _target_task_for_sequence(
        db,
        position=position,
        sequence=target_sequence,
        product_id=target_product_id,
        dimensions=dimensions,
        planned_qty=quantity,
        actor_id=actor_id,
    )

    from_location = await db.get(Section, balance.location_id)
    to_location = await db.get(Section, task.section_id)
    location_name = from_location.name if from_location else ""
    size_label = (
        f", размер {format_dimensions(dimensions)}" if dimensions is not None else ""
    )
    comment = (
        f"Автоподбор источника выдачи {issue_no}: «{location_name}» "
        f"({_fmt_qty(quantity)} шт.{size_label})"
    )
    # Источник называем, только когда он не совпадает с артикулом задания:
    # у группы из одного продукта комментарий остаётся прежним.
    if source_product_id != target_product_id and source_sku:
        comment += f", источник: {source_sku} (эквивалент)"

    transfer = Transfer(
        transfer_no=_transfer_no(),
        from_task_id=None,  # склада-источника касается только from_section_id (#282)
        to_task_id=task.id,
        from_section_id=balance.location_id,
        to_section_id=task.section_id,
        product_id=target_product_id,
        sent_quantity=quantity,
        status=TransferStatus.sent,
        sent_by=actor_id,
        sent_at=now,
        comment=comment,
        idempotency_key=idempotency_key,
        dimensions=dimensions,
        issue_no=issue_no,
    )
    db.add(transfer)
    await db.flush()

    actor_name = await _get_user_snapshot_name(db, actor_id)
    action = await action_journal_service.log(
        db,
        action_type="transfer_send",
        ref_id=transfer.id,
        actor=actor_name,
    )

    # Авто-приём: материал на участке получателя = выдан и готов к работе
    # (GLOSSARY «Авто-приём»), ровно как в transfer_send. `ready` здесь —
    # промежуточный мост: проекция не знает `waiting_previous`, итоговый
    # статус посчитает sync_work_task_status внутри record().
    transfer.status = TransferStatus.accepted
    transfer.accepted_quantity = quantity
    transfer.accepted_by = actor_id
    transfer.accepted_at = now
    if task.status == WorkTaskStatus.waiting_previous:
        task.status = WorkTaskStatus.ready
        await db.flush()

    await _stock_command_service.record(
        db,
        StockCommand(
            product_id=source_product_id,
            quantity=quantity,
            reason=Reason.TRANSFER_SEND,
            from_location_id=balance.location_id,
            to_location_id=task.section_id,
            dimensions=dimensions,
            quality_state=quality,
            to_quality_state=quality,
            completed_operations=completed_ops,
            # task_id/section_plan_line_id не проставляются: задания-источника
            # у складской выдачи нет (#282), а приписывать проводку fake-task
            # склада значило бы выдуманное «передано» в бюджете участка.
            transfer_id=transfer.id,
            action_id=action.id,
            created_by=actor_id,
            executor_user_id=actor_id,
            created_by_user_name=actor_name,
            executor_user_name=actor_name,
            source_ref=f"issue:{issue_no}",
            comment=comment,
            idempotency_key=f"{idempotency_key}:stock-send",
            performed_at=now,
            accounted_at=now,
            allow_negative=allow_negative,
        ),
    )
    await _stock_command_service.record(
        db,
        StockCommand(
            product_id=target_product_id,
            quantity=quantity,
            reason=Reason.TRANSFER_RECEIVE,
            from_location_id=None,
            to_location_id=None,
            dimensions=dimensions,
            quality_state=quality,
            to_quality_state=quality,
            completed_operations=completed_ops,
            task_id=task.id,
            section_plan_line_id=task.section_plan_line_id,
            transfer_id=transfer.id,
            action_id=action.id,
            created_by=actor_id,
            executor_user_id=actor_id,
            created_by_user_name=actor_name,
            executor_user_name=actor_name,
            source_ref=f"issue:{issue_no}",
            comment=comment,
            idempotency_key=f"{idempotency_key}:stock-receive",
            performed_at=now,
            accounted_at=now,
        ),
    )

    await _refresh_section_plan_line_cache(db, line.id)
    await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    # Сверх плана — расширяем плановое количество приёма, как transfer_send:
    # иначе оператор не сможет выдать и завершить полученный объём.
    from app.stock.services import StockProjectionManager

    to_cache = await StockProjectionManager().get_task_cache(db, task.id)
    await db.refresh(task)
    if to_cache["received_quantity"] > task.planned_quantity:
        task.planned_quantity = to_cache["received_quantity"]
        await db.flush()
        await _refresh_section_plan_line_cache(db, task.section_plan_line_id)

    return {
        "transfer_id": transfer.id,
        "transfer_no": transfer.transfer_no,
        "action_id": action.id,
        "from_location_id": balance.location_id,
        "from_location_name": location_name,
        "to_location_name": to_location.name if to_location else "",
        "to_task_id": task.id,
        "target_sequence": target_sequence,
        "quantity": quantity,
    }


async def _mark_jumped_stages(
    db: AsyncSession,
    *,
    position: PlanPosition,
    min_intake_sequence: int,
    issue_no: str,
) -> list[dict[str, Any]]:
    """Прыгнутые выдачей этапы → ``skipped`` с ``skipped_by_issue_no``.

    Прыгаются ВСЕ производственные этапы раньше самой дальней выдачи:
    материал, приехавший сразу на этап 5, уже прошёл 2–4, поэтому они не
    выполняются (#282, пример предпросмотра «этапы 2–4 снова в работу»).
    Этапы, которые сами приняли материал, не пропускаются — для них выдача
    обычная. Закрытые (completed/skipped/cancelled) не трогаем: пропуск не
    переигрывает выполненную работу, а чужой пропуск (например ручной, #207)
    не должен переприписываться нашим номером.
    """
    rows = (
        await db.execute(
            select(SectionPlanLine, WorkTask, RouteStage, Section)
            .join(WorkTask, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .join(RouteStage, RouteStage.id == SectionPlanLine.route_stage_id)
            .join(Section, Section.id == SectionPlanLine.section_id)
            .where(
                SectionPlanLine.plan_position_id == position.id,
                SectionPlanLine.sequence < min_intake_sequence,
                Section.type == SECTION_TYPE_PRODUCTION,
            )
            .order_by(SectionPlanLine.sequence)
        )
    ).all()
    marked: list[dict[str, Any]] = []
    for line, task, _stage, section in rows:
        if task.status in CLOSED_WORK_TASK_STATUSES:
            continue
        if task.status == WorkTaskStatus.in_progress:
            # материал уже двигается на этом этапе — пропуск стёр бы факт
            continue
        await skip_stage(
            db,
            section_plan_line_id=line.id,
            reason=SKIP_REASON_MATERIAL_READY,
            skipped_by_issue_no=issue_no,
        )
        marked.append(
            {
                "task_id": task.id,
                "section_plan_line_id": line.id,
                "sequence": line.sequence,
                "stage_name": section.name,
            }
        )
    return marked


async def execute_issue(
    db: AsyncSession,
    *,
    position: PlanPosition,
    product_id: int,
    required: Decimal,
    actor_id: int,
    idempotency_key: str,
    excluded_balance_ids: set[int] | None = None,
    shortage_strategy: ShortageStrategy | str = ShortageStrategy.partial,
) -> dict[str, Any]:
    """Выдача с автоподбором: N передач, один ``issue_no``, одна сессия.

    Возвращает итог операции (``collected``/``deficit`` — результат, а не
    ошибка) либо бросает ``ValueError`` с русским читаемым текстом:
    стратегия ``fail`` при нехватке, отказ на нулевом подборе. Техническая
    ошибка в середине — откат всей операции (ведёт вызывающий роут).
    """
    strategy = ShortageStrategy(shortage_strategy)
    required = Decimal(str(required))
    excluded = set(excluded_balance_ids or ())

    # Идемпотентный повтор всей операции: передачки созданы с ключом
    # ``{idempotency_key}:{i}`` — replay ищем по первой из них.
    replay = await _check_idempotency(
        db, idempotency_key=f"{idempotency_key}:0", entity_type=Transfer
    )
    if replay is not None and replay.issue_no:
        transfers = (
            await db.execute(
                select(Transfer).where(Transfer.issue_no == replay.issue_no).order_by(Transfer.id)
            )
        ).scalars().all()
        return {
            "issue_no": replay.issue_no,
            "idempotent_replay": True,
            "required": None,
            "collected": sum(
                (Decimal(t.sent_quantity) for t in transfers if t.status != TransferStatus.cancelled),
                ZERO,
            ),
            "deficit": None,
            "transfers": [
                {
                    "transfer_id": t.id,
                    "transfer_no": t.transfer_no,
                    "from_location_name": None,
                    "to_location_name": None,
                    "target_sequence": None,
                    "quantity": t.sent_quantity,
                }
                for t in transfers
            ],
            "skipped_stages": [],
        }

    # 1. Группа — один раз на вызов (кэш справочника), затем замок ВСЕХ
    # строк баланса группы на складах в системном порядке. Замок шире
    # кандидатов: подбор отсекает строки в SQL по `balance_qty > 0`, а
    # размер/признак операций фильтрует на python-стороне, поэтому строка,
    # пустая или ушедшая в минус на момент подбора (минус легален после
    # `negative_remainder`/`allow_negative`), может быть наполнена параллельной
    # операцией и войти в план. Залоченным должен быть весь ключ, по которому
    # план вообще способен ходить (группа эквивалентов × складские секции), а
    # не только предыдущая выборка кандидатов — иначе такая строка
    # вычерпывается без лока, а две выдачи на разные SKU одной группы
    # вычерпают одну кучу дважды (ADR-0073 §6). Размер/признак в замок не
    # уточняем: их python-канонизация живёт в source_selection, и повторять её
    # в SQL означало бы разъезд фильтров замка и плана. Порядок — по id:
    # детерминирован для обеих сторон гонки, взаимных блокировок не допускает.
    # План — один раз, под замком: повторный SELECT через ту же сессию не
    # перезаписывает атрибуты строк, уже лежащих в identity map, и «пересчёт
    # плана» посчитал бы количества первого прохода — двойное вычерпывание
    # вернулось бы незамеченным. `populate_existing` на запросе замка доносит
    # фактические `balance_qty` в сессию (в том числе для строк, прочитанных
    # вызывающим кодом до выдачи), поэтому и подбор, и последующее чтение
    # вычерпываемых балансов работают на свежих строках.
    cache = AliasGroupCache()
    alias_groups = await load_alias_groups(db, {product_id}, cache=cache)
    group = alias_groups.group_for(product_id)
    group_ids = group.product_ids if group is not None else (int(product_id),)

    stock_location_ids = (
        await db.execute(select(Section.id).where(Section.type.in_(STOCK_TYPES)))
    ).scalars().all()
    if stock_location_ids:
        await db.execute(
            select(StockBalance)
            .where(
                StockBalance.product_id.in_(group_ids),
                StockBalance.location_id.in_(stock_location_ids),
            )
            .order_by(StockBalance.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    plan = await build_issue_plan(
        db,
        position=position,
        product_id=product_id,
        required=required,
        excluded_balance_ids=excluded,
        group_ids=group_ids,
        alias_groups=alias_groups,
    )

    if plan.collected <= ZERO:
        if plan.candidates:
            names = [c.location_name for c in plan.candidates]
            raise ValueError(_shortage_reason(names, ZERO, required))
        raise ValueError(
            "Источник выдачи: ни на одном складе нет материала группы "
            "эквивалентов в нужном размере — выдавать нечего"
        )

    if plan.deficit > ZERO and strategy is ShortageStrategy.fail:
        names = [c.location_name for c in plan.candidates if c.take > 0]
        raise ValueError(_shortage_reason(names, plan.collected, required))

    issue_no = issue_no_now()
    now = datetime.now(UTC)

    # 2. Передачи по порядку подбора. Нехватку при ``negative_remainder``
    # добираем последней передачей: проводка с allow_negative уходит в минус
    # склада до закрытия последующей выдачей (#133).
    taken = [c for c in sorted(plan.candidates, key=lambda c: c.order) if c.take > 0]
    negative_index: int | None = None
    if plan.deficit > ZERO and strategy is ShortageStrategy.negative_remainder and taken:
        last = taken[-1]
        taken[-1] = replace(last, take=last.take + plan.deficit)
        negative_index = len(taken) - 1

    balances = {
        b.id: b
        for b in (
            await db.execute(select(StockBalance).where(StockBalance.id.in_([c.balance_id for c in taken])))
        ).scalars().all()
    }

    created: list[dict[str, Any]] = []
    for index, candidate in enumerate(taken):
        balance = balances.get(candidate.balance_id)
        if balance is None:  # pragma: no cover — строка залочена, исчезнуть не может
            raise ValueError("Источник выдачи: склад исчез из остатков при выдаче")
        result = await _record_issue_transfer(
            db,
            position=position,
            product_id=product_id,
            issue_no=issue_no,
            balance=balance,
            quantity=Decimal(candidate.take),
            target_sequence=candidate.target_sequence,
            actor_id=actor_id,
            idempotency_key=f"{idempotency_key}:{index}",
            now=now,
            allow_negative=(negative_index is not None and index == negative_index),
            source_sku=candidate.sku,
        )
        created.append(result)

    # 3. Прыгнутые этапы — «Пропущено» с нашим номером выдачи.
    skipped: list[dict[str, Any]] = []
    if created:
        min_intake = min(t["target_sequence"] for t in created)
        skipped = await _mark_jumped_stages(
            db, position=position, min_intake_sequence=min_intake, issue_no=issue_no
        )

    await db.flush()
    issued = sum((Decimal(str(t["quantity"])) for t in created), ZERO)
    return {
        "issue_no": issue_no,
        "idempotent_replay": False,
        "required": required,
        "collected": issued,
        "deficit": max(ZERO, required - issued),
        "transfers": created,
        "skipped_stages": skipped,
    }


def issue_summary_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Итог выдачи для API/UI: числа человекочитаемые, id в тексте нет."""
    return {
        "issue_no": result["issue_no"],
        "required": None if result.get("required") is None else _fmt_qty(result["required"]),
        "collected": None if result.get("collected") is None else _fmt_qty(result["collected"]),
        "deficit": None if result.get("deficit") is None else _fmt_qty(result["deficit"]),
        "transfers": [
            {
                "transfer_id": t["transfer_id"],
                "transfer_no": t["transfer_no"],
                "from_location_name": t.get("from_location_name"),
                "to_location_name": t.get("to_location_name"),
                "target_sequence": t.get("target_sequence"),
                "quantity": _fmt_qty(t["quantity"]),
            }
            for t in result.get("transfers", [])
        ],
        "skipped_stages": result.get("skipped_stages", []),
    }


# ─── Отмена выдачи целиком ─────────────────────────────────────────────────


async def _issue_transfers(db: AsyncSession, issue_no: str) -> list[Transfer]:
    return list(
        (
            await db.execute(
                select(Transfer).where(Transfer.issue_no == issue_no).order_by(Transfer.id)
            )
        ).scalars().all()
    )


async def _issue_skipped_tasks(db: AsyncSession, issue_no: str) -> list[WorkTask]:
    return list(
        (
            await db.execute(
                select(WorkTask)
                .where(WorkTask.skipped_by_issue_no == issue_no)
                .order_by(WorkTask.id)
            )
        ).scalars().all()
    )


async def _stage_label(db: AsyncSession, task: WorkTask) -> tuple[int, str]:
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    section = await db.get(Section, task.section_id)
    sequence = line.sequence if line is not None else 0
    return sequence, (section.name if section else "")


async def _acceptance_blocker(db: AsyncSession, transfer: Transfer) -> str | None:
    """Причина отказа отменять выдачу целиком — по одной передаче.

    «Принята» в явном смысле (``partially_accepted``/отклонена/скорректирована)
    или на приёмном этапе уже есть факты исполнения (завершено/отклонено
    хоть что-то) — вернуть материал нельзя, не породив минус.
    """
    if transfer.status in {TransferStatus.partially_accepted, TransferStatus.rejected, TransferStatus.amended}:
        return (
            f"Передача {transfer.transfer_no} принята частично или отклонена — "
            "выдачу целиком не отменить"
        )
    task = await db.get(WorkTask, transfer.to_task_id)
    if task is None:
        return None
    from app.stock.services import StockProjectionManager

    cache = await StockProjectionManager().get_task_cache(db, task.id)
    consumed = Decimal(str(cache["completed_quantity"])) + Decimal(str(cache["rejected_quantity"]))
    if consumed > ZERO:
        _seq, name = await _stage_label(db, task)
        return (
            f"На этапе «{name}» уже есть завершённая или бракованная работа "
            f"({_fmt_qty(consumed)} шт.) — выдачу целиком не отменить"
        )
    return None


async def preview_issue_cancellation(db: AsyncSession, *, issue_no: str) -> dict[str, Any]:
    """Что вернёт отмена: «вернём 40 на Хранилище Б, 12 на В, этапы 2–4 снова в работу».

    Блокировка — текстом причины (#282): если хоть одна передача уже принята
    в смысле фактов исполнения, целиком выдача не отменяется.
    """
    transfers = await _issue_transfers(db, issue_no)
    if not transfers:
        raise ValueError("Выдача с таким номером не найдена")
    live = [t for t in transfers if t.status != TransferStatus.cancelled]

    returns: list[dict[str, Any]] = []
    blockers: list[str] = []
    for transfer in live:
        location = await db.get(Section, transfer.from_section_id)
        returns.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "location_id": transfer.from_section_id,
                "location_name": location.name if location else "",
                "quantity": _fmt_qty(transfer.sent_quantity),
            }
        )
        blocker = await _acceptance_blocker(db, transfer)
        if blocker is not None:
            blockers.append(blocker)

    stages: list[dict[str, Any]] = []
    for task in await _issue_skipped_tasks(db, issue_no):
        sequence, name = await _stage_label(db, task)
        stages.append({"task_id": task.id, "sequence": sequence, "stage_name": name})
    stages.sort(key=lambda item: item["sequence"])

    return {
        "issue_no": issue_no,
        "returns": returns,
        "stages": stages,
        "can_cancel": not blockers,
        "reason": None if not blockers else "; ".join(blockers),
        "summary": _cancellation_summary(returns, stages, blockers),
    }


def _cancellation_summary(
    returns: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    blockers: list[str],
) -> str:
    """Текст предпросмотра: «вернём 40 на Хранилище Б, 12 на В, этапы 2–4 снова в работу»."""
    parts: list[str] = []
    if returns:
        tail = ", ".join(
            f"{item['quantity']} на «{item['location_name']}»" for item in returns
        )
        parts.append(f"вернём {tail}")
    sequences = sorted({int(item["sequence"]) for item in stages})
    if sequences:
        span = str(sequences[0]) if len(sequences) == 1 else f"{sequences[0]}–{sequences[-1]}"
        parts.append(f"этапы {span} снова в работу")
    head = ", ".join(parts)
    if blockers:
        reason = "; ".join(blockers)
        return f"{head}. Отменить нельзя: {reason}" if head else f"Отменить нельзя: {reason}"
    return head


async def cancel_issue(
    db: AsyncSession,
    *,
    issue_no: str,
    actor_id: int,
    comment: str | None = None,
) -> dict[str, Any]:
    """Отмена выдачи целиком: передачи по одной + снятие СВОИХ пропусков.

    ``cancel_transfer`` откатывает каждую передачу через её собственный
    ``transfer_send`` Action (ADR-0019), поэтому частичная отмена остаётся
    возможной и в «Отмене действий» поштучно. Пропуски снимаются только те,
    где ``skipped_by_issue_no`` равен этому номеру (#282).
    """
    from app.transfers.services import cancel_transfer

    transfers = await _issue_transfers(db, issue_no)
    if not transfers:
        raise ValueError("Выдача с таким номером не найдена")
    live = [t for t in transfers if t.status != TransferStatus.cancelled]
    if not live:
        # Явный отказ вместо тихого no-op: «отменить ещё раз» не должно
        # выглядеть как успех, даже когда удвоенного возврата уже нет (#282).
        raise ValueError(f"Выдача {issue_no} уже отменена — повторная отмена невозможна")

    blockers: list[str] = []
    for transfer in live:
        blocker = await _acceptance_blocker(db, transfer)
        if blocker is not None:
            blockers.append(blocker)
    if blockers:
        raise ValueError("Выдачу целиком не отменить: " + "; ".join(blockers))

    cancelled: list[dict[str, Any]] = []
    for transfer in live:
        result = await cancel_transfer(
            db, transfer_id=transfer.id, actor_id=actor_id, comment=comment
        )
        cancelled.append(
            {
                "transfer_id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": result.get("status"),
            }
        )

    restored: list[dict[str, Any]] = []
    for task in await _issue_skipped_tasks(db, issue_no):
        sequence, name = await _stage_label(db, task)
        await _restore_skipped_task(db, task)
        restored.append(
            {
                "task_id": task.id,
                "sequence": sequence,
                "stage_name": name,
            }
        )

    await db.flush()
    return {
        "issue_no": issue_no,
        "cancelled_transfers": cancelled,
        "restored_stages": restored,
    }


async def _restore_skipped_task(db: AsyncSession, task: WorkTask) -> None:
    """Снять пропуск, поставленный нашей выдачей.

    Статус — как при релизе: ``ready``, если раньше по маршруту нет
    незакрытого этапа, иначе ``waiting_previous``. Проводок на этапе нет
    (проекции его не касаются), поэтому статус ставим прямо.
    """
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is None:
        raise ValueError("Выдача: у пропущенного этапа нет строки плана")
    open_predecessor = await db.scalar(
        select(WorkTask.id)
        .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
        .where(
            SectionPlanLine.plan_position_id == line.plan_position_id,
            SectionPlanLine.sequence < line.sequence,
            SectionPlanLine.route_stage_id.isnot(None),
            WorkTask.status.notin_(CLOSED_WORK_TASK_STATUSES),
        )
    )
    task.status = (
        WorkTaskStatus.waiting_previous if open_predecessor else WorkTaskStatus.ready
    )
    task.skip_reason = None
    task.skipped_by_issue_no = None
    await db.flush()
    await _refresh_section_plan_line_cache(db, line.id)
