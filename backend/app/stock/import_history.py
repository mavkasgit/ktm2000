"""Сервис истории импорта остатков (ADR-0052, ADR-0053).

Три операции, различаемые по смыслу, а не по формулировке кнопки:

* **посмотреть** — прочитать батч и его строки (только чтение);
* **откатить** — зеркально скомпенсировать проводки батча по узлу журнала
  действий. Остатки возвращаются к состоянию до импорта, запись остаётся со
  статусом ``rolled_back``. Гейты: **LIFO по складу** (ADR-0053 п.1) и
  **покрытие** (ADR-0019 п.8) — если материал после импорта израсходован,
  компенсации нечем покрыть, откат падает с ``CoverageShortfall``;
* **скрыть** — мягкое удаление записи из списка. Ledger и узел журнала не
  трогаются: проводки append-only, а узлы журнала не удаляются никогда
  (ADR-0019 §7).

LIFO — **UI-гейт** (ADR-0053 п.4), как в ADR-0025 п.2 для плана: здесь он
реализован как ``can_rollback``, чтобы кнопка и предпросмотр не расходились.
Серверный гейт, который остаётся по-настоящему, один — покрытие: он читает
реальный баланс и потому не обходится клиентом.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ImportFile
from app.models.action_journal import Action, ActionStatus
from app.models.section import Section
from app.models.user import User
from app.stock.import_models import (
    StockImportBatch,
    StockImportBatchStatus,
    StockImportRow,
)
from app.stock.models import QualityState, StockBalance

#: Тип узла журнала действий, которым помечается батч импорта остатков.
REMAINDER_ACTION_TYPE = "import_remainders"

#: Минимальная длина причины удаления — как у ``import_batch_force_delete``.
MIN_REASON_LENGTH = 3

BLOCK_NOT_LAST = "batch_not_last_for_location"
BLOCK_ALREADY_ROLLED_BACK = "batch_already_rolled_back"
BLOCK_LEGACY_NO_LOCATION = "batch_location_unknown"
BLOCK_HIDDEN = "batch_hidden"


class ImportHistoryError(Exception):
    """Ошибка операции над историей импорта (→ 400/404/409 на API)."""

    def __init__(self, message: str, *, code: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(slots=True)
class BatchView:
    """Строка списка истории импортов остатков."""

    batch_id: int
    action_id: int
    status: str
    legacy: bool
    clear_existing: bool
    filename: str | None
    file_id: int | None
    sheet_name: str | None
    location_id: int | None
    location_name: str | None
    total_rows: int
    imported_rows: int
    skipped_rows: int
    created_at: datetime
    created_by_name: str | None
    rolled_back_at: datetime | None
    deleted_at: datetime | None
    can_rollback: bool
    rollback_blocked_reason: str | None


@dataclass(slots=True)
class RowView:
    """Строка импорта в диалоге «посмотреть»."""

    row_id: int
    source_row_number: int
    sku: str
    matched_sku: str | None
    product_id: int | None
    product_sku: str | None
    product_name: str | None
    quantity: Decimal | None
    dimensions_label: str
    target_section_id: int | None
    target_section_name: str | None
    quality_state: str | None
    # Пятая ось ключа остатка (ADR-0055): без неё две строки одного артикула,
    # склада и размера в «посмотреть» выглядят как дубль с разными остатками.
    completed_operations: list[str] | None
    status: str
    errors: list[str]
    warnings: list[str]
    raw_values: list[str]
    current_balance: Decimal | None





async def list_batches(
    db: AsyncSession,
    *,
    location_id: int | None = None,
    include_hidden: bool = False,
) -> list[BatchView]:
    """Список батчей импорта остатков, новые сверху.

    ``location_id`` фильтрует по складу; ``include_hidden`` показывает и
    мягко удалённые (по умолчанию скрытые не видны — это и есть смысл
    ``deleted_at``).
    """
    stmt = (
        select(StockImportBatch, ImportFile, Section, Action)
        .outerjoin(ImportFile, StockImportBatch.file_id == ImportFile.id)
        .outerjoin(Section, StockImportBatch.location_id == Section.id)
        # Статус батча — проекция статуса узла журнала, а не самостоятельное
        # поле: откат возможен и из истории импортов, и из общего журнала
        # действий. Два независимых статуса рано или поздно покажут откатанный
        # батч откатываемым; источник истины по откату — узел журнала.
        .outerjoin(Action, StockImportBatch.action_id == Action.id)
        .order_by(StockImportBatch.id.desc())
    )
    if location_id is not None:
        stmt = stmt.where(StockImportBatch.location_id == location_id)
    if not include_hidden:
        stmt = stmt.where(StockImportBatch.deleted_at.is_(None))

    rows = (await db.execute(stmt)).all()

    # Последний живой батч каждого склада — единственная цель LIFO. Считаем
    # по всем батчам склада, а не по отфильтрованной выборке: фильтр
    # ``location_id`` мог скрыть последний батч, и тогда откат older-батча
    # выглядел бы разрешённым только из-за фильтра.
    last_by_location: dict[int, int] = {}
    for batch, _f, _s, action in rows:
        if (
            batch.location_id is None
            or _is_rolled_back(batch, action)
            or batch.deleted_at is not None
        ):
            continue
        current = last_by_location.get(batch.location_id)
        if current is None or batch.id > current:
            last_by_location[batch.location_id] = batch.id

    return [
        _batch_view(batch, file, section, last_by_location, action)
        for batch, file, section, action in rows
    ]


def _is_rolled_back(
    batch: StockImportBatch, action: Action | None
) -> bool:
    """Откатан ли батч — по узлу журнала, с оглядкой на собственное поле.

    Узел журнала — источник истины (ADR-0019 §7), а ``status`` батча
    проставляется путём отката из истории. Проверяем оба: обратный откат
    недоступен, но и неоткатанный по собственному полю батч с неактивным
    узлом (откатнули из общего журнала) обязан читаться как откатанный.
    """
    if batch.status == StockImportBatchStatus.ROLLED_BACK:
        return True
    return action is not None and action.status != ActionStatus.ACTIVE


def _batch_view(
    batch: StockImportBatch,
    file: ImportFile | None,
    section: Section | None,
    last_by_location: dict[int, int],
    action: Action | None = None,
) -> BatchView:
    rolled_back = _is_rolled_back(batch, action)
    blocked: str | None = None
    if rolled_back:
        blocked = BLOCK_ALREADY_ROLLED_BACK
    elif batch.location_id is None:
        # Legacy-батч: склад не сохранился, область LIFO неизвестна, но узел
        # журнала откатывается как есть (ADR-0053 п.1, следствие).
        blocked = BLOCK_LEGACY_NO_LOCATION
    elif last_by_location.get(batch.location_id) != batch.id:
        blocked = BLOCK_NOT_LAST
    elif batch.deleted_at is not None:
        blocked = BLOCK_HIDDEN
    return BatchView(
        batch_id=batch.id,
        action_id=batch.action_id,
        status=(
            StockImportBatchStatus.ROLLED_BACK.value
            if rolled_back
            else StockImportBatchStatus.APPLIED.value
        ),
        legacy=batch.legacy,
        clear_existing=batch.clear_existing,
        filename=file.original_filename if file else None,
        file_id=batch.file_id,
        sheet_name=batch.sheet_name,
        location_id=batch.location_id,
        location_name=section.name if section else None,
        total_rows=batch.total_rows,
        imported_rows=batch.imported_rows,
        skipped_rows=batch.skipped_rows,
        created_at=batch.created_at,
        created_by_name=batch.created_by_name,
        rolled_back_at=batch.rolled_back_at,
        deleted_at=batch.deleted_at,
        can_rollback=blocked is None,
        rollback_blocked_reason=blocked,
    )


async def get_batch(db: AsyncSession, batch_id: int) -> StockImportBatch:
    batch = await db.get(StockImportBatch, batch_id)
    if batch is None:
        raise ImportHistoryError(
            f"Батч импорта id={batch_id} не найден", code="not_found", status_code=404
        )
    return batch


async def get_batch_rows(
    db: AsyncSession, batch_id: int
) -> list[RowView]:
    """Строки импорта с текущим остатком по каждой строке.

    «Текущий остаток» — ответ на вопрос после отката («а что там сейчас?»).
    Читается из проекции ``stock_balances`` по полному ключу строки
    ``(product, section, quality, dimensions, completed_operations)`` — при
    совпадении только первых четырёх осей две строки одного участка с разными
    операциями (ADR-0055) получили бы одну сумму, и «посмотреть» показало бы
    не тот остаток, который батч завёл. Для откатанного батча это и есть
    сумма уже без его вклада.

    Сам признак строки попадает в ``RowView.completed_operations``: две строки
    одного артикула и склада с разными остатками без оси на экране — два
    неотличимых дубля, а с осью — две разные группы остатка (ADR-0055).
    """
    from app.models.product import Product
    from app.domain.dimensions import format_dimensions

    # Проверка существования батча (get_batch бросает not_found) — побочный
    # эффект сохраняется, результат здесь не нужен.
    await get_batch(db, batch_id)
    stmt = (
        select(StockImportRow, Product, Section)
        .outerjoin(Product, StockImportRow.product_id == Product.id)
        .outerjoin(Section, StockImportRow.target_section_id == Section.id)
        .where(StockImportRow.batch_id == batch_id)
        .order_by(StockImportRow.source_row_number)
    )
    rows = (await db.execute(stmt)).all()

    # Остатки батча забираем одним запросом по всем ключам строк, а не по
    # запросу на строку: их может быть тысячи, и «посмотреть» должно
    # открываться мгновенно. Совпадение размеров — канонический
    # ``dimensions_match_clause``, а не ``contains`` (это подмножество, и
    # ``{"length_mm": 2700}`` совпало бы с ``{"length_mm": 2700, "width_mm": 100}``).
    # Признак операций — пятая ось ключа баланса (ADR-0055): без неё в
    # группировке две строки одного участка с разными операциями получили бы
    # одну сумму, и «посмотреть» показало бы не тот остаток, который завёл батч.
    wanted: dict[tuple[int, int, str, str, str], dict | None] = {}
    for row, _p, _s in rows:
        if row.product_id is None or row.target_section_id is None:
            continue
        wanted[(
            row.product_id,
            row.target_section_id,
            row.quality_state or QualityState.GOOD.value,
            _dims_key(row.dimensions),
            _ops_key(row.completed_operations),
        )] = row.dimensions

    balances: dict[tuple[int, int, str, str, str], Decimal] = {}
    if wanted:
        product_ids = {k[0] for k in wanted}
        location_ids = {k[1] for k in wanted}
        quality_states = {k[2] for k in wanted}
        bq = (
            select(
                StockBalance.product_id,
                StockBalance.location_id,
                StockBalance.quality_state,
                StockBalance.dimensions,
                StockBalance.completed_operations,
                func.coalesce(func.sum(StockBalance.balance_qty), 0),
            )
            .where(
                StockBalance.product_id.in_(product_ids),
                StockBalance.location_id.in_(location_ids),
                StockBalance.quality_state.in_(quality_states),
            )
            .group_by(
                StockBalance.product_id,
                StockBalance.location_id,
                StockBalance.quality_state,
                StockBalance.dimensions,
                StockBalance.completed_operations,
            )
        )
        for pid, lid, qs, dims, ops, qty in (await db.execute(bq)).all():
            balances[(pid, lid, qs, _dims_key(dims), _ops_key(ops))] = Decimal(
                str(qty or 0)
            )

    return [
        RowView(
            row_id=row.id,
            source_row_number=row.source_row_number,
            sku=row.sku,
            matched_sku=row.matched_sku,
            product_id=row.product_id,
            product_sku=product.sku if product else None,
            product_name=product.name if product else None,
            quantity=row.quantity,
            dimensions_label=format_dimensions(row.dimensions),
            target_section_id=row.target_section_id,
            target_section_name=section.name if section else None,
            quality_state=row.quality_state,
            completed_operations=(
                list(row.completed_operations)
                if row.completed_operations is not None
                else None
            ),
            status=str(row.status),
            errors=list(row.errors or []),
            warnings=list(row.warnings or []),
            raw_values=list(row.raw_values or []),
            current_balance=balances.get(
                (
                    row.product_id,
                    row.target_section_id,
                    (row.quality_state or QualityState.GOOD.value),
                    _dims_key(row.dimensions),
                    _ops_key(row.completed_operations),
                )
            )
            if row.product_id is not None and row.target_section_id is not None
            else None,
        )
        for row, product, section in rows
    ]


async def import_batch_rollback_blockers(
    db: AsyncSession, action_id: int
) -> list:
    """Блокеры отката батча импорта остатков по его состоянию (ADR-0053).

    Живёт в компенсаторе, а не в API: сервис отката зовут не только хендлеры
    (``production_plan_service`` тоже), и «последний на складе» — правило
    предметной области, а не права доступа. Право (роль) проверяется в API.

    Узла журнала без строки батча (импорт до миграции, до бэкфилла) гейт не
    трогает: блокировать откат того, что откатывается и сейчас, незачем.
    """
    from app.reversal.base import CheckBlocker

    row = (
        await db.execute(
            select(StockImportBatch, Action)
            .outerjoin(Action, StockImportBatch.action_id == Action.id)
            .where(StockImportBatch.action_id == action_id)
        )
    ).first()
    if row is None:
        return []
    batch, action = row
    if _is_rolled_back(batch, action):
        return [
            CheckBlocker(
                kind="already_reversed",
                detail="батч импорта уже откатан",
            )
        ]
    if batch.deleted_at is not None:
        return [
            CheckBlocker(
                kind="not_allowed",
                detail="батч скрыт из списка — сначала верните его",
            )
        ]
    if batch.location_id is None:
        # Склад legacy-батча не сохранился, область LIFO неизвестна.
        # Откат по нему не запрещён: узел журнала откатывается как есть, а
        # зеркальные компенсации полностью определяются самими проводками.
        return []
    newer = await _has_newer_live_batch(db, batch)
    if newer is not None:
        return [
            CheckBlocker(
                kind="not_allowed",
                detail="откатить можно только последний импорт этого склада",
            )
        ]
    return []


async def _has_newer_live_batch(
    db: AsyncSession, batch: StockImportBatch
) -> int | None:
    """Id более позднего неоткатанного батча того же склада (ADR-0053 п.1).

    «Живой» = не откатан (по узлу журнала либо по собственному полю) и не
    скрыт: и тот, и другой уже не может быть отката��, поэтому «последний» для
    следующего отката — последний из оставшихся.
    """
    newer = await db.scalar(
        select(func.max(StockImportBatch.id))
        .join(Action, StockImportBatch.action_id == Action.id)
        .where(
            StockImportBatch.location_id == batch.location_id,
            StockImportBatch.status == StockImportBatchStatus.APPLIED,
            StockImportBatch.deleted_at.is_(None),
            StockImportBatch.id > batch.id,
            Action.status == ActionStatus.ACTIVE,
        )
    )
    return newer


def _dims_key(dims: dict | None) -> str:
    """Канонический ключ размеров строки импорта (как в ledger)."""
    if dims is None:
        return ""
    return ",".join(f"{k}={dims[k]}" for k in sorted(dims))


def _ops_key(ops: list | None) -> str:
    """Канонический ключ признака операций строки импорта (ADR-0055).

    ``json.dumps`` различает три состояния записи: ``null`` («состояние не
    зафиксировано»), ``[]`` («маршрут пройден, операций не было») и список
    кодов. Схлопывание ``NULL`` и ``[]`` в один ключ объединило бы две РАЗНЫЕ
    строки остатка в одну — ровно тот дефект, ради которого ось операций и
    вводилась. Список приходит каноническим (отсортированным без дублей) из
    ``_row_completed_operations``, поэтому порядок обхода на ключ не влияет.
    """
    return json.dumps(ops, ensure_ascii=False)


async def hide_batch(
    db: AsyncSession, batch_id: int, *, user: User | None, reason: str | None
) -> StockImportBatch:
    """Мягко убрать батч из списка (ADR-0052 п.5).

    Ledger не трогается: проводки остаются в силе, а узел журнала действий по
    ADR-0019 §7 не удаляется никогда. Повторный вызов идемпотентен.
    """
    batch = await get_batch(db, batch_id)
    if batch.deleted_at is not None:
        return batch
    if reason is not None and len(reason.strip()) < MIN_REASON_LENGTH:
        raise ImportHistoryError(
            f"Причина удаления короче {MIN_REASON_LENGTH} символов",
            code="reason_too_short",
            status_code=400,
        )
    batch.deleted_at = datetime.now(timezone.utc)
    batch.deleted_by = user.id if user else None
    batch.delete_reason = reason
    await db.commit()
    return batch


async def mark_rolled_back(
    db: AsyncSession,
    batch: StockImportBatch,
    *,
    user: User | None,
) -> StockImportBatch:
    """Перевести батч в ``rolled_back`` после успешной компенсации."""
    batch.status = StockImportBatchStatus.ROLLED_BACK
    batch.rolled_back_at = datetime.now(timezone.utc)
    batch.rolled_back_by = user.id if user else None
    await db.commit()
    return batch


async def assert_rollback_allowed(db: AsyncSession, batch: StockImportBatch) -> None:
    """Серверный гейт отката: батч должен быть последним живым на своём складе.

    Гейт дублирует правило UI (ADR-0053 п.1, п.4) осознанно: LIFO нужно, чтобы
    не вернуть остаток к состоянию, которого на складе не было никогда
    (``clear_existing`` двух батчей подряд). Покрытие проверяется отдельно и
    в самом компенсаторе.
    """
    action = await db.get(Action, batch.action_id)
    if _is_rolled_back(batch, action):
        raise ImportHistoryError(
            "Батч уже откатан", code=BLOCK_ALREADY_ROLLED_BACK
        )
    if batch.deleted_at is not None:
        raise ImportHistoryError(
            "Батч скрыт из списка — сначала верните его", code=BLOCK_HIDDEN
        )
    if batch.location_id is None:
        raise ImportHistoryError(
            "У батча не сохранился склад: откат по нему недоступен",
            code=BLOCK_LEGACY_NO_LOCATION,
        )
    newer = await _has_newer_live_batch(db, batch)
    if newer is not None:
        raise ImportHistoryError(
            "Откатить можно только последний импорт этого склада",
            code=BLOCK_NOT_LAST,
        )
