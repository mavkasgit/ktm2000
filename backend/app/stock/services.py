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

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, Section
from app.models.work_task import WorkTask
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
    quality_state: QualityState = QualityState.good
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
        ``(product, location, quality_state)``. from_quality_state описывает
        состояние материала до перехода (на исходной локации),
        to_quality_state — после (на целевой). Если баланс стал 0 —
        строка удаляется (инкубатор: ck_stock_balances_nonzero).
        """
        # from_location: исходящий материал в from_quality_state
        if tx.from_location_id is not None:
            await self._recompute_balance(
                session, tx.product_id, tx.from_location_id, tx.from_quality_state
            )
        # to_location: входящий материал в to_quality_state
        if tx.to_location_id is not None:
            await self._recompute_balance(
                session, tx.product_id, tx.to_location_id, tx.to_quality_state
            )

    async def _recompute_balance(
        self,
        session: AsyncSession,
        product_id: int,
        location_id: int,
        quality_state: QualityState,
    ) -> None:
        """Пересчёт одной строки баланса из ledger (атомарный UPSERT).

        Считаем SUM(incoming) - SUM(outgoing) по ledger для данного ключа.
        Если 0 — удаляем строку; иначе UPSERT.
        """
        incoming = await session.execute(
            select(StockTransaction.quantity)
            .where(
                StockTransaction.product_id == product_id,
                StockTransaction.to_location_id == location_id,
                StockTransaction.to_quality_state == quality_state,
            )
        )
        outgoing = await session.execute(
            select(StockTransaction.quantity)
            .where(
                StockTransaction.product_id == product_id,
                StockTransaction.from_location_id == location_id,
                StockTransaction.from_quality_state == quality_state,
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
        await session.execute(StockBalance.__table__.delete())  # wipe
        result = await session.execute(
            select(
                StockTransaction.product_id,
                StockTransaction.from_location_id,
                StockTransaction.to_location_id,
                StockTransaction.from_quality_state,
                StockTransaction.to_quality_state,
                StockTransaction.quantity,
            )
        )
        agg: dict[tuple[int, int, QualityState], Decimal] = {}
        for product_id, from_loc, to_loc, from_qs, to_qs, qty in result:
            if to_loc is not None:
                key = (product_id, to_loc, to_qs)
                agg[key] = agg.get(key, Decimal("0")) + qty
            if from_loc is not None:
                key = (product_id, from_loc, from_qs)
                agg[key] = agg.get(key, Decimal("0")) - qty
        for (product_id, location_id, qs), balance in agg.items():
            if balance == 0:
                continue
            session.add(
                StockBalance(
                    product_id=product_id,
                    location_id=location_id,
                    quality_state=qs,
                    balance_qty=balance,
                    refreshed_at=datetime.now(),
                )
            )
        return len(agg)

    async def refresh_task_projection(self, session: AsyncSession, tx: StockTransaction) -> None:
        """Обновление WorkTask.cached_* из StockTransaction ledger.

        На Этапе 2: для ``transfer_send`` / ``transfer_receive``
        пересчитывает ``cached_transferred_quantity`` /
        ``cached_received_quantity`` из SUM StockTransaction
        (оригиналы +Q, компенсации −Q).
        """
        if tx.reason not in (Reason.transfer_send, Reason.transfer_receive):
            return
        if tx.task_id is None:
            return
        from sqlalchemy import case, func

        # Net quantity: оригинала +quantity, компенсации −quantity
        _net = func.sum(
            case(
                (StockTransaction.compensates_tx_id.is_(None), StockTransaction.quantity),
                else_=-StockTransaction.quantity,
            )
        )
        transferred = await session.scalar(
            select(func.coalesce(_net, 0))
            .where(
                StockTransaction.task_id == tx.task_id,
                StockTransaction.reason == Reason.transfer_send,
            )
        ) or 0
        received = await session.scalar(
            select(func.coalesce(_net, 0))
            .where(
                StockTransaction.task_id == tx.task_id,
                StockTransaction.reason == Reason.transfer_receive,
            )
        ) or 0
        await session.execute(
            update(WorkTask)
            .where(WorkTask.id == tx.task_id)
            .values(
                cached_transferred_quantity=transferred,
                cached_received_quantity=received,
            )
        )

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
        1. Валидация (product exists, quantity > 0, locations differ, reason
           consistent with quality_state).
        2. Идемпотентность по ``idempotency_key`` — если уже есть транзакция
           с таким ключом, вернуть её (не создавать дубль).
        3. INSERT StockTransaction.
        4. ``projection_manager.stock_changed(tx)`` — синхронно в той же
           транзакции.

        Возвращает созданную (или существующую по идемпотентности)
        транзакцию.
        """
        await self._validate(session, cmd)

        if cmd.idempotency_key is not None:
            existing = await session.execute(
                select(StockTransaction).where(
                    StockTransaction.idempotency_key == cmd.idempotency_key
                )
            )
            prior = existing.scalar_one_or_none()
            if prior is not None:
                return prior

        tx = StockTransaction(
            product_id=cmd.product_id,
            from_location_id=cmd.from_location_id,
            to_location_id=cmd.to_location_id,
            quantity=cmd.quantity,
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
        if cmd.quantity <= 0:
            raise StockValidationError(f"quantity must be > 0, got {cmd.quantity}")
        if cmd.from_location_id is None and cmd.to_location_id is None:
            raise StockValidationError(
                "at least one of from_location_id / to_location_id must be set"
            )
        if (
            cmd.from_location_id is not None
            and cmd.to_location_id is not None
            and cmd.from_location_id == cmd.to_location_id
        ):
            raise StockValidationError(
                f"from_location_id and to_location_id must differ, got {cmd.from_location_id}"
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
        if cmd.reason == Reason.scrap:
            if cmd.quality_state != QualityState.good or to_qs != QualityState.scrap:
                raise StockValidationError(
                    f"reason=scrap requires from_quality=good, to_quality=scrap; "
                    f"got from={cmd.quality_state.value}, to={to_qs.value}"
                )
        if cmd.reason == Reason.rework:
            if to_qs != QualityState.rework:
                raise StockValidationError(
                    f"reason=rework requires to_quality=rework, got {to_qs.value}"
                )
        if cmd.reason == Reason.complete and to_qs != QualityState.good:
            raise StockValidationError(
                f"reason=complete requires to_quality=good, got {to_qs.value}"
            )
        # created_by mandatory at DB level — пока не enforced здесь (тесты могут
        # передавать 0/null); будет tightened когда все call sites подключатся.
