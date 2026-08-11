"""Сервисный слой Stock Ledger (Этап 1).

``StockCommand`` — явная команда пользователя/бизнес-операции. Содержит
интент: откуда, куда, сколько, по какой причине, в каком качестве.
Никакой скрытой магии: автопотребление, перевыполнение, переделка — это
отдельные параметры команды, инициируемые UI, а не внутренние каскады.

``StockCommandService.record()`` — единственный путь записи в ledger.
Валидирует, проверяет идемпотентность, создаёт ``StockTransaction`` и
синхронно вызывает ``StockProjectionManager.stock_changed()`` в рамках
той же транзакции с БД.

``StockProjectionManager`` — единая точка обновления всех проекций
(баланс, задача, plan-line, качество). Компромисс между чистой
command→event→subscribers шиной и прямолинейными cascades: одна точка,
но без каскадов A→B→C→D→E. См. AGENTS.md → принцип 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, cast as tcast

from sqlalchemy import Select, cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dimensions import (
    DimensionsValidationError,
    canonicalize_dimensions,
    format_dimensions,
)
from app.models import Product, Section
from app.models.work_task import WorkTask
from app.stock.task_cache import (
    compute_remaining,
    compute_task_available,
    effective_issued_quantity,
)
from app.stock.transfer_ledger import net_received_sq, net_transferred_sq
from app.stock.models import (
    QualityState,
    Reason,
    StockBalance,
    StockTransaction,
)


class StockValidationError(ValueError):
    """Нарушение бизнес-инварианта при записи в ledger.

    Поднимается до любых INSERT — транзакция остаётся чистой, никаких
    частичных записей.
    """


def dimensions_match_clause(column, dims: dict | None):
    """SQL-условие «габарит равен dims» с учётом NULL (legacy-группа).

    ``dims`` ожидается в канонической форме (canonicalize_dimensions);
    jsonb-равенство в PostgreSQL не зависит от порядка ключей.

    ``None`` (безразмерные штуки) — матчит и SQL ``NULL``, и JSON ``null``:
    asyncpg при явном ``None`` в JSONB-колонке может сохранить ``'null'::jsonb``
    вместо SQL ``NULL``, поэтому только ``IS NULL`` пропускал бы такие строки.
    """
    if dims is None:
        return or_(column.is_(None), column == text("'null'::jsonb"))
    return column == cast(dims, JSONB)


def _dimensions_hash_key(dims: dict | None) -> str | None:
    """Хешируемый ключ группировки для dict-габарита (in-memory агрегации)."""
    if dims is None:
        return None
    return json.dumps(dims, sort_keys=True, ensure_ascii=False)


@dataclass
class StockCommand:
    """Интент записи движения материала в ledger.

    Минимально обязательные поля: ``product_id``, ``quantity``, ``reason``.
    Как минимум один из ``from_location_id`` / ``to_location_id`` должен
    быть задан (CHECK на уровне таблицы). Остальные поля — контекст
    конкретной операции.
    """

    product_id: int
    quantity: Decimal
    reason: Reason
    from_location_id: int | None = None
    to_location_id: int | None = None
    # Габарит движения (ADR-0001): dict в любой форме — record()
    # приводит к канонической через canonicalize_dimensions;
    # None = безразмерные штуки (legacy-группа баланса).
    dimensions: dict[str, Any] | None = None
    quality_state: QualityState = QualityState.GOOD
    # Результирующее качество (на to_location). По умолчанию = quality_state
    # (без изменения состояния). Для SCRAP: quality_state=good, to_quality_state=scrap.
    to_quality_state: QualityState | None = None
    task_id: int | None = None
    transfer_id: int | None = None
    section_plan_line_id: int | None = None
    compensates_tx_id: int | None = None
    created_by: int | None = None
    executor_user_id: int | None = None
    created_by_user_name: str | None = None
    executor_user_name: str | None = None
    idempotency_key: str | None = None
    source_ref: str | None = None
    comment: str | None = None
    performed_at: datetime | None = None
    accounted_at: datetime | None = None
    is_post_factum: bool = False
    # Подтверждённое пользователем перевыполнение (см. принцип 2 AGENTS.md):
    # если fact > plan, операция явная, фиксируется в журнале.
    overcomplete_acknowledged: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class StockProjectionManager:
    """Единая точка обновления проекций после записи в ledger.

    Метод ``stock_changed`` вызывается синхронно из ``StockCommandService``
    в рамках текущей транзакции с БД. Каждая подсистема обновляется
    независимо — никаких перекрёстных каскадов.

    На Этапе 1 реализован только ``refresh_balance``. Остальные —
    no-op заглушки, подключаются на Этапах 4-5 (WorkTask.completed_qty,
    SectionPlanLine, Defect).
    """

    async def stock_changed(self, session: AsyncSession, tx: StockTransaction) -> None:
        await self.refresh_balance(session, tx)
        await self.refresh_task_projection(session, tx)
        await self.refresh_spl_projection(session, tx)
        await self.refresh_quality_view(session, tx)

    async def refresh_balance(self, session: AsyncSession, tx: StockTransaction) -> None:
        """Инкрементальное обновление StockBalance для затронутых локаций.

        Баланс = SUM(incoming) - SUM(outgoing) по ключу
        ``(product, location, quality_state, dimensions)``. from_quality_state
        описывает состояние материала до перехода (на исходной локации),
        to_quality_state — после (на целевой). Если баланс стал 0 —
        строка удаляется (инкубатор: ck_stock_balances_nonzero).
        """
        # from_location: исходящий материал в from_quality_state
        if tx.from_location_id is not None:
            await self._recompute_balance(
                session, tx.product_id, tx.from_location_id, tx.from_quality_state,
                tx.dimensions,
            )
        # to_location: входящий материал в to_quality_state
        if tx.to_location_id is not None:
            await self._recompute_balance(
                session, tx.product_id, tx.to_location_id, tx.to_quality_state,
                tx.dimensions,
            )

    async def _recompute_balance(
        self,
        session: AsyncSession,
        product_id: int,
        location_id: int,
        quality_state: QualityState,
        dimensions: dict | None,
    ) -> None:
        """Пересчёт одной строки баланса из ledger (атомарный UPSERT).

        Считаем SUM(incoming) - SUM(outgoing) по ledger для данного ключа
        (включая габарит; NULL-габарит — отдельная legacy-группа).
        Если 0 — удаляем строку; иначе UPSERT.
        """
        incoming = await session.execute(
            select(StockTransaction.quantity)
            .where(
                StockTransaction.product_id == product_id,
                StockTransaction.to_location_id == location_id,
                StockTransaction.to_quality_state == quality_state,
                dimensions_match_clause(StockTransaction.dimensions, dimensions),
            )
        )
        outgoing = await session.execute(
            select(StockTransaction.quantity)
            .where(
                StockTransaction.product_id == product_id,
                StockTransaction.from_location_id == location_id,
                StockTransaction.from_quality_state == quality_state,
                dimensions_match_clause(StockTransaction.dimensions, dimensions),
            )
        )
        in_sum = sum((r[0] for r in incoming), Decimal("0"))
        out_sum = sum((r[0] for r in outgoing), Decimal("0"))
        balance = in_sum - out_sum

        existing = await session.execute(
            select(StockBalance).where(
                StockBalance.product_id == product_id,
                StockBalance.location_id == location_id,
                StockBalance.quality_state == quality_state,
                dimensions_match_clause(StockBalance.dimensions, dimensions),
            )
        )
        row = existing.scalar_one_or_none()
        if balance == 0:
            if row is not None:
                await session.delete(row)
            return
        if row is None:
            row = StockBalance(
                product_id=product_id,
                location_id=location_id,
                quality_state=quality_state,
                dimensions=dimensions,
                balance_qty=balance,
                refreshed_at=datetime.now(),
            )
            session.add(row)
        else:
            row.balance_qty = balance
            row.refreshed_at = datetime.now()

    async def rebuild_all_balances(self, session: AsyncSession) -> int:
        """Полный пересчёт всех строк StockBalance из ledger.

        Используется в diagnostics/миграциях для сверки. Возвращает
        количество строк баланса после пересчёта.
        """
        # ORM-delete: autoflush доносит незаписанные изменения проекции,
        # а объекты в identity map синхронизируются с удалением (wipe).
        await session.execute(delete(StockBalance))
        result = await session.execute(
            select(
                StockTransaction.product_id,
                StockTransaction.from_location_id,
                StockTransaction.to_location_id,
                StockTransaction.from_quality_state,
                StockTransaction.to_quality_state,
                StockTransaction.dimensions,
                StockTransaction.quantity,
            )
        )
        # Ключ агрегата включает хешируемый слепок габарита;
        # сам dict храним отдельно для записи в строку баланса.
        agg: dict[tuple[int, int, QualityState, str | None], Decimal] = {}
        dims_by_key: dict[str | None, dict | None] = {}
        for product_id, from_loc, to_loc, from_qs, to_qs, dims, qty in result:
            dims_key = _dimensions_hash_key(dims)
            dims_by_key.setdefault(dims_key, dims)
            if to_loc is not None:
                key = (product_id, to_loc, to_qs, dims_key)
                agg[key] = agg.get(key, Decimal("0")) + qty
            if from_loc is not None:
                key = (product_id, from_loc, from_qs, dims_key)
                agg[key] = agg.get(key, Decimal("0")) - qty
        for (product_id, location_id, qs, dims_key), balance in agg.items():
            if balance == 0:
                continue
            session.add(
                StockBalance(
                    product_id=product_id,
                    location_id=location_id,
                    quality_state=qs,
                    dimensions=dims_by_key.get(dims_key),
                    balance_qty=balance,
                    refreshed_at=datetime.now(),
                )
            )
        return len(agg)

    async def refresh_task_projection(self, session: AsyncSession, tx: StockTransaction) -> None:
        """No-op — cached_* колонки удалены, используйте get_task_cache()."""
        return None

    async def _compute_task_cache(
        self, session: AsyncSession, task_id: int,
    ) -> dict | None:
        """Вычислить cache-словарь для одной задачи из StockTransaction ledger.

        Возвращает dict с 7 полями или None если задача не найдена.
        """
        task = await session.get(WorkTask, task_id)
        if task is None:
            return None

        from app.models.internal_plan import SectionPlanLine
        line = await session.get(SectionPlanLine, task.section_plan_line_id)
        is_first_stage = (line is not None and line.sequence == 1)

        # Один GROUP BY запрос
        rows = await session.execute(
            select(
                StockTransaction.reason,
                func.sum(StockTransaction.quantity).label("qty"),
            )
            .where(StockTransaction.task_id == task_id)
            .group_by(StockTransaction.reason)
        )
        sums: dict[str, Decimal] = {}
        for reason_val, qty in rows:
            sums[reason_val] = (sums.get(reason_val) or Decimal("0")) + qty

        def _sum_reason(reason: Reason) -> Decimal:
            return sums.get(reason.value) or Decimal("0")

        # Net transfer_send/receive с учётом компенсаций — примитив transfer_ledger.
        # TOTAL по задаче (dims=None → без dimension-фильтра), как было в кэше.
        send_sq = net_transferred_sq(alias="task_cache_send_sq")
        recv_sq = net_received_sq(alias="task_cache_recv_sq")
        transferred = (
            await session.scalar(
                select(send_sq.c.net_quantity).where(send_sq.c.task_id == task_id)
            )
        ) or Decimal("0")
        received = (
            await session.scalar(
                select(recv_sq.c.net_quantity).where(recv_sq.c.task_id == task_id)
            )
        ) or Decimal("0")

        completed = _sum_reason(Reason.COMPLETE)
        scrapped = _sum_reason(Reason.SCRAP)
        returned = _sum_reason(Reason.RETURN_TO_STOCK)
        rejected = scrapped  # DefectDecision на Этапе 5
        issued = effective_issued_quantity(received=received)

        available = compute_task_available(
            planned_quantity=task.planned_quantity,
            received_quantity=received,
            issued_quantity=issued,
            returned_quantity=returned,
            is_first_stage=is_first_stage,
        )
        remaining = compute_remaining(
            planned_quantity=task.planned_quantity,
            transferred_quantity=transferred,
        )

        return {
            "available_quantity": available,
            "issued_quantity": issued,
            "completed_quantity": completed,
            "transferred_quantity": transferred,
            "received_quantity": received,
            "rejected_quantity": rejected,
            "remaining_quantity": remaining,
        }

    async def get_task_cache(self, session: AsyncSession, task_id: int) -> dict:
        """Вернуть cache-словарь для задачи (вычисляется из StockTransaction).

        Совместимая форма со старым API-ответом (фронт не мигрирован до Этапа 6).
        """
        result = await self._compute_task_cache(session, task_id)
        if result is None:
            return {
                "available_quantity": Decimal("0"),
                "issued_quantity": Decimal("0"),
                "completed_quantity": Decimal("0"),
                "transferred_quantity": Decimal("0"),
                "received_quantity": Decimal("0"),
                "rejected_quantity": Decimal("0"),
                "remaining_quantity": Decimal("0"),
            }
        return result

    async def get_tasks_cache_bulk(self, session: AsyncSession, task_ids: list[int]) -> dict[int, dict]:
        """Вернуть dict {task_id: cache_dict} для списка задач, один GROUP BY запрос.

        Для bulk-запросов (queries_sections, queries_spg).
        """
        if not task_ids:
            return {}

        # Загружаем задачи и линии
        tasks = (await session.execute(
            select(WorkTask).where(WorkTask.id.in_(task_ids))
        )).scalars().all()
        task_map = {t.id: t for t in tasks}

        from app.models.internal_plan import SectionPlanLine
        lines = (await session.execute(
            select(SectionPlanLine).where(
                SectionPlanLine.id.in_([t.section_plan_line_id for t in tasks])
            )
        )).scalars().all()
        line_map = {l.id: l for l in lines}

        # GROUP BY reason, task_id
        rows = await session.execute(
            select(
                StockTransaction.task_id,
                StockTransaction.reason,
                func.sum(StockTransaction.quantity).label("qty"),
            )
            .where(StockTransaction.task_id.in_(task_ids))
            .group_by(StockTransaction.task_id, StockTransaction.reason)
        )

        sums: dict[int, dict[str, Decimal]] = {}
        for tid, reason_val, qty in rows:
            if tid not in sums:
                sums[tid] = {}
            sums[tid][reason_val] = (sums[tid].get(reason_val) or Decimal("0")) + qty

        # Net для transfer_send/receive с compensations — примитив transfer_ledger.
        # TOTAL по задачам (dims=None → без dimension-фильтра), один запрос.
        send_sq = tcast(Select, net_transferred_sq()).where(
            StockTransaction.task_id.in_(task_ids)
        ).subquery("bulk_send_sq")
        recv_sq = tcast(Select, net_received_sq()).where(
            StockTransaction.task_id.in_(task_ids)
        ).subquery("bulk_recv_sq")
        net_rows = await session.execute(
            select(
                func.coalesce(send_sq.c.task_id, recv_sq.c.task_id).label("task_id"),
                func.coalesce(send_sq.c.net_quantity, 0).label("send_net"),
                func.coalesce(recv_sq.c.net_quantity, 0).label("recv_net"),
            )
            .select_from(send_sq)
            .outerjoin(recv_sq, recv_sq.c.task_id == send_sq.c.task_id, full=True)
        )
        send_net_by_task: dict[int, Decimal] = {}
        recv_net_by_task: dict[int, Decimal] = {}
        for tid, send_net, recv_net in net_rows:
            send_net_by_task[tid] = send_net
            recv_net_by_task[tid] = recv_net

        result: dict[int, dict] = {}
        for tid in task_ids:
            task = task_map.get(tid)
            if task is None:
                result[tid] = {
                    "available_quantity": Decimal("0"),
                    "issued_quantity": Decimal("0"),
                    "completed_quantity": Decimal("0"),
                    "transferred_quantity": Decimal("0"),
                    "received_quantity": Decimal("0"),
                    "rejected_quantity": Decimal("0"),
                    "remaining_quantity": Decimal("0"),
                }
                continue

            line = line_map.get(task.section_plan_line_id)
            is_first_stage = (line is not None and line.sequence == 1)
            t_sums = sums.get(tid, {})

            def _val(s: dict, key: Reason) -> Decimal:
                return s.get(key.value) or Decimal("0")

            completed = _val(t_sums, Reason.COMPLETE)
            scrapped = _val(t_sums, Reason.SCRAP)
            returned = _val(t_sums, Reason.RETURN_TO_STOCK)
            transferred = send_net_by_task.get(tid, Decimal("0"))
            received = recv_net_by_task.get(tid, Decimal("0"))
            rejected = scrapped
            issued = effective_issued_quantity(received=received)

            available = compute_task_available(
                planned_quantity=task.planned_quantity,
                received_quantity=received,
                issued_quantity=issued,
                returned_quantity=returned,
                is_first_stage=is_first_stage,
            )
            remaining = compute_remaining(
                planned_quantity=task.planned_quantity,
                transferred_quantity=transferred,
            )

            result[tid] = {
                "available_quantity": available,
                "issued_quantity": issued,
                "completed_quantity": completed,
                "transferred_quantity": transferred,
                "received_quantity": received,
                "rejected_quantity": rejected,
                "remaining_quantity": remaining,
            }

        return result

    async def refresh_spl_projection(self, session: AsyncSession, tx: StockTransaction) -> None:
        """Этап 4: SectionPlanLine cache из ledger. Пока no-op."""
        return None

    async def refresh_quality_view(self, session: AsyncSession, tx: StockTransaction) -> None:
        """Этап 5: агрегаты по качеству. Пока no-op."""
        return None


class StockCommandService:
    """Единственный путь записи в StockTransaction ledger.

    Все бизнес-операции (issue, complete, return, transfer, scrap, rework)
    подготавливают ``StockCommand`` и вызывают ``record()``. Никаких
    прямых INSERT в StockTransaction вне этого сервиса.
    """

    def __init__(self, projection_manager: StockProjectionManager | None = None) -> None:
        self._projection_manager = projection_manager or StockProjectionManager()

    async def record(self, session: AsyncSession, cmd: StockCommand) -> StockTransaction:
        """Записать движение в ledger + обновить проекции.

        Шаги:
        1. Идемпотентность по ``idempotency_key`` — если уже есть транзакция
           с таким ключом, вернуть её (не создавать дубль).
        2. Валидация (product exists, quantity > 0, locations differ, reason
           consistent with quality_state).
        3. INSERT StockTransaction.
        4. ``projection_manager.stock_changed(tx)`` — синхронно в той же
           транзакции.

        Возвращает созданную (или существующую по идемпотентности)
        транзакцию.
        """
        if cmd.idempotency_key is not None:
            existing = await session.execute(
                select(StockTransaction).where(
                    StockTransaction.idempotency_key == cmd.idempotency_key
                )
            )
            prior = existing.scalar_one_or_none()
            if prior is not None:
                return prior

        # Приведение габарита к канонической форме до валидации/INSERT:
        # ledger хранит только каноническую форму ({} → None).
        try:
            cmd.dimensions = canonicalize_dimensions(cmd.dimensions)
        except DimensionsValidationError as exc:
            raise StockValidationError(f"invalid dimensions: {exc}") from exc

        await self._validate(session, cmd)

        tx = StockTransaction(
            product_id=cmd.product_id,
            from_location_id=cmd.from_location_id,
            to_location_id=cmd.to_location_id,
            quantity=cmd.quantity,
            dimensions=cmd.dimensions,
            reason=cmd.reason,
            from_quality_state=cmd.quality_state,
            to_quality_state=cmd.to_quality_state or cmd.quality_state,
            task_id=cmd.task_id,
            transfer_id=cmd.transfer_id,
            section_plan_line_id=cmd.section_plan_line_id,
            compensates_tx_id=cmd.compensates_tx_id,
            source_ref=cmd.source_ref,
            idempotency_key=cmd.idempotency_key,
            comment=cmd.comment,
            created_by=cmd.created_by,  # type: ignore[arg-type]
            executor_user_id=cmd.executor_user_id,
            created_by_user_name=cmd.created_by_user_name,
            executor_user_name=cmd.executor_user_name,
            performed_at=cmd.performed_at,
            accounted_at=cmd.accounted_at,
            is_post_factum=cmd.is_post_factum,
        )
        session.add(tx)
        await session.flush()  # получить tx.id для compensates_tx_id и projection

        await self._projection_manager.stock_changed(session, tx)
        return tx

    async def _validate(self, session: AsyncSession, cmd: StockCommand) -> None:
        if cmd.reason == Reason.ISSUE_TO_WORK:
            raise StockValidationError(
                "reason=issue_to_work is no longer allowed; use TRANSFER_SEND/TRANSFER_RECEIVE"
            )
        if cmd.quantity <= 0:
            raise StockValidationError(f"quantity must be > 0, got {cmd.quantity}")
        if cmd.from_location_id is None and cmd.to_location_id is None:
            if cmd.reason != Reason.TRANSFER_RECEIVE:
                raise StockValidationError(
                    "at least one of from_location_id / to_location_id must be set"
                )
        # Some reasons are "state changes" on the same location
        # (complete, scrap, rework) — allow same from/to for these.
        _state_change_reasons = {
            Reason.COMPLETE,
            Reason.SCRAP,
            Reason.REWORK,
            Reason.FINAL_RELEASE,
        }
        if cmd.reason not in _state_change_reasons:
            if (
                cmd.from_location_id is not None
                and cmd.to_location_id is not None
                and cmd.from_location_id == cmd.to_location_id
            ):
                raise StockValidationError(
                    f"from_location_id and to_location_id must differ for reason={cmd.reason.value}, "
                    f"got {cmd.from_location_id}"
                )
        # Product existence
        prod = await session.get(Product, cmd.product_id)
        if prod is None:
            raise StockValidationError(f"product_id={cmd.product_id} not found")
        # Locations existence
        for label, loc_id in (("from_location_id", cmd.from_location_id),
                              ("to_location_id", cmd.to_location_id)):
            if loc_id is None:
                continue
            loc = await session.get(Section, loc_id)
            if loc is None:
                raise StockValidationError(f"{label}={loc_id} not found")
        # Reason ↔ quality_state consistency
        to_qs = cmd.to_quality_state or cmd.quality_state
        if cmd.reason == Reason.SCRAP:
            if cmd.quality_state != QualityState.GOOD or to_qs != QualityState.SCRAP:
                raise StockValidationError(
                    f"reason=scrap requires from_quality=good, to_quality=scrap; "
                    f"got from={cmd.quality_state.value}, to={to_qs.value}"
                )
        if cmd.reason == Reason.REWORK:
            if to_qs != QualityState.REWORK:
                raise StockValidationError(
                    f"reason=rework requires to_quality=rework, got {to_qs.value}"
                )
        if cmd.reason == Reason.COMPLETE and to_qs != QualityState.GOOD:
            raise StockValidationError(
                f"reason=complete requires to_quality=good, got {to_qs.value}"
            )

        # Net-zero operations (from == to AND качество не меняется, напр.
        # COMPLETE на нетрансформирующем этапе) не двигают баланс: одна
        # транзакция даёт +qty (to) и -qty (from) в одну строку баланса,
        # поэтому negative-check для них избыточен. Если качество меняется
        # (SCRAP/REWORK с from == to) — операция НЕ net-zero, проверка нужна.
        to_qs_net = cmd.to_quality_state or cmd.quality_state
        is_net_zero = (
            cmd.from_location_id is not None
            and cmd.from_location_id == cmd.to_location_id
            and cmd.quality_state == to_qs_net
        )
        if cmd.from_location_id is not None and cmd.compensates_tx_id is None and not is_net_zero:
            balance_result = await session.execute(
                select(StockBalance).where(
                    StockBalance.product_id == cmd.product_id,
                    StockBalance.location_id == cmd.from_location_id,
                    StockBalance.quality_state == cmd.quality_state,
                    dimensions_match_clause(StockBalance.dimensions, cmd.dimensions),
                )
            )
            balance_row = balance_result.scalar_one_or_none()
            current_balance = balance_row.balance_qty if balance_row is not None else Decimal("0")
            if current_balance < cmd.quantity:
                # Габарит в ошибке (тикет #89): «без указания длины» вместо
                # прочерка — понятнее оператору, какую строку остатка искать.
                dims_label = (
                    format_dimensions(cmd.dimensions)
                    if cmd.dimensions is not None
                    else "без указания длины"
                )
                raise StockValidationError(
                    f"Insufficient stock for product_id={cmd.product_id} at location_id={cmd.from_location_id} "
                    f"(quality={cmd.quality_state.value}, dimensions={dims_label}): "
                    f"required {cmd.quantity}, available {current_balance}"
                )

        # created_by mandatory at DB level — пока не enforced здесь (тесты могут
        # передавать 0/null); будет tightened когда все call sites подключатся.
