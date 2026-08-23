"""FastAPI router for the Stock Ledger.

Mounted at ``/api/stock``. Read-only endpoints для сверки и будущего
UI-перехода (Этап 6). Старый ``/api/spg/*`` остаётся live до Этапа 7 —
никаких ``if legacy`` флагов, версии живут параллельно.

Endpoints:

  * ``GET /stock/balance``             — список строк StockBalance
    с фильтрами ``product_id`` / ``location_id`` / ``quality_state``,
    поиском, сортировкой и пагинацией ``limit`` / ``offset``.
  * ``GET /stock/balance/by-product/{product_id}`` — все балансы
    конкретного продукта по локациям.
  * ``GET /stock/transactions``        — лента StockTransaction с
    фильтрами ``product_id`` / ``transfer_id`` / ``task_id`` / ``reason``
    и пагинацией ``limit`` / ``offset``.

Все эндпоинты требуют только reader-роль: это аудит/сверка, не мутация.
Запись идёт исключительно через сервисы доменов (transfer_send и т.д.),
прямого write-API здесь нет — см. принцип «единственный путь записи» в
``app/stock/services.py::StockCommandService``.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.types import String
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.domain.dimensions import format_dimensions
from app.models.import_template import ImportTemplate
from app.models.product import Product
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.user import User
from app.stock.models import (
    QualityState,
    Reason,
    StockBalance,
    StockTransaction,
)
from app.stock.services import StockCommand, StockCommandService, StockValidationError
from app.services.action_journal_service import action_journal_service
from app.stock.import_service import (
    ImportResult,
    RemainderItem,
    SheetSummary,
    apply_remainders_import,
    generate_remainders_template_for_location,
    parse_remainders_clipboard,
    parse_remainders_excel,
    parse_operations_from_comment,
    query_remainder_preview_items,
    resolve_completed_stages,
    resolve_operations_dictionary,
    resolve_remainder_dimensions,
    resolve_target_section,
)
from app.stock.import_service import _lookup_products as _lookup_remainder_products
from fastapi.responses import StreamingResponse
from io import BytesIO

router = APIRouter(prefix="/stock", tags=["stock-ledger"])


async def _load_template_column_mapping(
    db: AsyncSession, template_id: int | None
) -> dict | None:
    """column_mapping шаблона импорта или None (→ дефолт «маппинг остатков» из JSON)."""
    if template_id is None:
        return None
    template = await db.get(ImportTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=404, detail=f"ImportTemplate id={template_id} not found"
        )
    return dict(template.column_mapping or {})


async def _parse_remainder_import_source(
    *,
    file: UploadFile | None,
    clipboard_text: str | None,
    sheet_index: int,
    row_selection: str | None,
    column_mapping: dict | None = None,
) -> tuple[str, int, list[RemainderItem], SheetSummary]:
    """Parse remainder rows from an uploaded Excel file or clipboard text."""
    has_file = file is not None and file.filename
    has_clipboard = bool(clipboard_text and clipboard_text.strip())

    if has_file and has_clipboard:
        raise HTTPException(
            status_code=422,
            detail="Укажите либо файл, либо данные из буфера обмена",
        )
    if not has_file and not has_clipboard:
        raise HTTPException(
            status_code=422,
            detail="Укажите файл или вставьте данные из буфера обмена",
        )

    try:
        if has_clipboard:
            return await parse_remainders_clipboard(
                clipboard_text or "", row_selection, column_mapping
            )
        content = await file.read()  # type: ignore[union-attr]
        return await parse_remainders_excel(
            content, sheet_index, row_selection, column_mapping
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ─── Schemas ──────────────────────────────────────────────────────────────────


class StockBalanceCompletedStageOut(BaseModel):
    sequence: int
    section_code: str
    section_name: str
    section_icon: str | None = None
    section_icon_color: str | None = None
    operation_code: str | None
    operation_name: str
    op_icon: str | None = None
    op_icon_color: str | None = None
    is_significant: bool = True


class StockBalanceOut(BaseModel):
    id: int
    product_id: int
    product_sku: str | None = None
    location_id: int
    location_name: str | None = None
    quality_state: QualityState
    balance_qty: str  # Decimal → str для стабильной сериализации
    # Габаритная группа остатка (ADR-0001); None = legacy/безразмерные.
    dimensions: dict | None = None
    dimensions_label: str = "—"
    completed_stages: list[StockBalanceCompletedStageOut] = Field(default_factory=list)
    refreshed_at: str | None = None

    class Config:
        from_attributes = True


class StockBalancesListResponse(BaseModel):
    balances: list[StockBalanceOut]
    total: int
    limit: int
    offset: int


class StockTransactionsListResponse(BaseModel):
    transactions: list["StockTransactionOut"]
    total: int
    limit: int
    offset: int


class StockTransactionOut(BaseModel):
    id: int
    product_id: int
    from_location_id: int | None
    from_location_name: str | None = None
    to_location_id: int | None
    to_location_name: str | None = None
    quantity: str
    dimensions: dict | None = None
    dimensions_label: str = "—"
    reason: Reason
    from_quality_state: QualityState
    to_quality_state: QualityState
    task_id: int | None
    transfer_id: int | None
    section_plan_line_id: int | None
    reverses_id: int | None
    source_ref: str | None
    idempotency_key: str | None
    comment: str | None
    created_by: int | None
    executor_user_id: int | None
    created_by_user_name: str | None
    executor_user_name: str | None
    performed_at: str | None
    accounted_at: str | None
    is_post_factum: bool
    created_at: str | None

    class Config:
        from_attributes = True


class StockAdjustmentIn(BaseModel):
    """Payload для ручной корректировки остатков (POST /stock/adjustment).

    ``reason`` определяет направление движения:
    * ``adjustment_in`` / ``manual_in`` — приход на ``location_id`` (to_location)
    * ``adjustment_out`` / ``manual_out`` — расход с ``location_id`` (from_location)
    """
    product_id: int
    location_id: int
    quantity: float = Field(gt=0)
    reason: Reason
    quality_state: QualityState = QualityState.GOOD
    # Габарит (ADR-0001), например {"length_mm": 2700}; некорректная
    # форма → 422 (канонизация в StockCommandService.record()).
    dimensions: dict | None = None
    comment: str | None = None


class StockAdjustmentOut(BaseModel):
    id: int
    reason: Reason
    quantity: str
    created_at: str | None = None


# ─── Balance ──────────────────────────────────────────────────────────────────

BALANCE_SORT_FIELDS = frozenset({
    "sku",
    "quantity",
    "operations",
    "quality",
    "location",
    "product_id",
})


def _latest_manual_in_comment_expr():
    """Коррелированный подзапрос: комментарий последнего MANUAL_IN по ключу баланса."""
    return (
        select(StockTransaction.comment)
        .where(
            StockTransaction.reason == Reason.MANUAL_IN,
            StockTransaction.reverses_id.is_(None),
            StockTransaction.product_id == StockBalance.product_id,
            StockTransaction.to_location_id == StockBalance.location_id,
            StockTransaction.to_quality_state == StockBalance.quality_state,
        )
        .order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc())
        .limit(1)
        .correlate(StockBalance)
        .scalar_subquery()
    )


def _balance_base_stmt():
    return (
        select(StockBalance, Section.name, Product.sku)
        .outerjoin(Section, Section.id == StockBalance.location_id)
        .outerjoin(Product, Product.id == StockBalance.product_id)
    )


def _apply_balance_filters(
    stmt,
    *,
    product_id: Optional[int],
    location_id: Optional[int],
    location_ids: Optional[list[int]],
    quality_state: Optional[QualityState],
    search: Optional[str],
    sku: Optional[str],
    quantity: Optional[str],
    quality: Optional[str],
    location: Optional[str],
    operations: Optional[str],
):
    if product_id is not None:
        stmt = stmt.where(StockBalance.product_id == product_id)
    if location_id is not None:
        stmt = stmt.where(StockBalance.location_id == location_id)
    elif location_ids:
        stmt = stmt.where(StockBalance.location_id.in_(location_ids))
    if quality_state is not None:
        stmt = stmt.where(StockBalance.quality_state == quality_state)
    if sku is not None:
        stmt = stmt.where(Product.sku.ilike(f"%{sku}%"))
    if quantity is not None:
        stmt = stmt.where(cast(StockBalance.balance_qty, String).ilike(f"%{quantity}%"))
    if quality is not None:
        stmt = stmt.where(cast(StockBalance.quality_state, String).ilike(f"%{quality}%"))
    if location is not None:
        location_like = f"%{location}%"
        stmt = stmt.where(
            or_(
                Section.name.ilike(location_like),
                Section.code.ilike(location_like),
            )
        )
    if operations is not None:
        latest_comment = _latest_manual_in_comment_expr()
        stmt = stmt.where(latest_comment.ilike(f"%{operations}%"))
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Product.sku.ilike(search_like),
                cast(StockBalance.product_id, String).ilike(search_like),
                Section.name.ilike(search_like),
                Section.code.ilike(search_like),
            )
        )
    return stmt


def _apply_balance_sort(stmt, *, sort_by: str, sort_order: str):
    resolved_sort_by = sort_by if sort_by in BALANCE_SORT_FIELDS else "sku"
    order_column = Product.sku
    if resolved_sort_by == "quantity":
        order_column = StockBalance.balance_qty
    elif resolved_sort_by == "quality":
        order_column = StockBalance.quality_state
    elif resolved_sort_by == "location":
        order_column = Section.name
    elif resolved_sort_by == "product_id":
        order_column = StockBalance.product_id
    elif resolved_sort_by == "operations":
        order_column = _latest_manual_in_comment_expr()

    if sort_order == "desc":
        return stmt.order_by(
            order_column.desc().nulls_last(),
            StockBalance.product_id.desc(),
            StockBalance.location_id.desc(),
            StockBalance.id.desc(),
        )
    return stmt.order_by(
        order_column.asc().nulls_last(),
        StockBalance.product_id.asc(),
        StockBalance.location_id.asc(),
        StockBalance.id.asc(),
    )


def _serialize_balance(
    row: StockBalance,
    location_name: str | None,
    product_sku: str | None = None,
    completed_stages: list[StockBalanceCompletedStageOut] | None = None,
) -> StockBalanceOut:
    return StockBalanceOut(
        id=row.id,
        product_id=row.product_id,
        product_sku=product_sku,
        location_id=row.location_id,
        location_name=location_name,
        quality_state=row.quality_state,
        balance_qty=str(row.balance_qty),
        dimensions=row.dimensions,
        dimensions_label=format_dimensions(row.dimensions),
        completed_stages=completed_stages or [],
        refreshed_at=row.refreshed_at.isoformat() if row.refreshed_at else None,
    )


_OPERATION_COMMENT_REASONS = (
    Reason.MANUAL_IN,
    Reason.TRANSFER_RECEIVE,
    Reason.COMPLETE,
)


async def _serialize_balances_with_operations(
    db: AsyncSession,
    rows: list[tuple[StockBalance, str | None, str | None]],
) -> list[StockBalanceOut]:
    if not rows:
        return []

    product_ids = {row.product_id for row, _, _ in rows}
    stmt = (
        select(StockTransaction)
        .where(
            StockTransaction.reason.in_(_OPERATION_COMMENT_REASONS),
            StockTransaction.reverses_id.is_(None),
            StockTransaction.product_id.in_(product_ids),
        )
        .order_by(StockTransaction.created_at.desc())
    )
    txs = (await db.execute(stmt)).scalars().all()

    transfer_ids = {
        tx.transfer_id
        for tx in txs
        if tx.transfer_id is not None and tx.reason == Reason.TRANSFER_RECEIVE
    }
    transfers_by_id: dict[int, Transfer] = {}
    if transfer_ids:
        transfers = (
            await db.execute(select(Transfer).where(Transfer.id.in_(transfer_ids)))
        ).scalars().all()
        transfers_by_id = {transfer.id: transfer for transfer in transfers}

    comment_by_key: dict[tuple[int, int, QualityState], str | None] = {}
    for tx in txs:
        if not parse_operations_from_comment(tx.comment):
            continue
        location_id = tx.to_location_id
        if location_id is None and tx.reason == Reason.TRANSFER_RECEIVE and tx.transfer_id:
            transfer = transfers_by_id.get(tx.transfer_id)
            if transfer is not None:
                location_id = transfer.to_section_id
        if location_id is None:
            continue
        key = (tx.product_id, location_id, tx.to_quality_state)
        if key not in comment_by_key:
            comment_by_key[key] = tx.comment

    ops_dict = await resolve_operations_dictionary(db)
    result: list[StockBalanceOut] = []
    for row, location_name, product_sku in rows:
        key = (row.product_id, row.location_id, row.quality_state)
        comment = comment_by_key.get(key)
        stages_out: list[StockBalanceCompletedStageOut] = []
        raw_ops = parse_operations_from_comment(comment)
        if raw_ops:
            stages_raw = await resolve_completed_stages(
                db,
                ", ".join(raw_ops),
                ops_dict,
            )
            stages_out = [StockBalanceCompletedStageOut(**stage) for stage in stages_raw]
        result.append(_serialize_balance(row, location_name, product_sku, stages_out))
    return result


@router.get("/balance", response_model=StockBalancesListResponse)
async def list_balances(
    product_id: Optional[int] = Query(default=None),
    location_id: Optional[int] = Query(default=None),
    location_ids: Optional[list[int]] = Query(default=None),
    quality_state: Optional[QualityState] = Query(default=None),
    search: Optional[str] = Query(
        default=None,
        description="Поиск по артикулу, product_id, названию участка",
    ),
    sku: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on product SKU",
    ),
    quantity: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on balance quantity",
    ),
    quality: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on quality_state enum value",
    ),
    location: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on section name or code",
    ),
    operations: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on latest MANUAL_IN comment",
    ),
    sort_by: str = Query(default="sku"),
    sort_order: str = Query(default="asc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> StockBalancesListResponse:
    """Список строк баланса (projection из StockTransaction).

    Без фильтров возвращает все ненулевые строки. Баланс = SUM(in) - SUM(out)
    по ключу ``(product, location, quality_state)``; нулевые строки не
    хранятся (см. ``StockProjectionManager.refresh_balance``).
    """
    stmt = _balance_base_stmt()
    stmt = _apply_balance_filters(
        stmt,
        product_id=product_id,
        location_id=location_id,
        location_ids=location_ids,
        quality_state=quality_state,
        search=search,
        sku=sku,
        quantity=quantity,
        quality=quality,
        location=location,
        operations=operations,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = _apply_balance_sort(stmt, sort_by=sort_by, sort_order=sort_order)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    balances = await _serialize_balances_with_operations(db, list(result.all()))
    return StockBalancesListResponse(
        balances=balances,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/balance/by-product/{product_id}", response_model=list[StockBalanceOut])
async def list_balances_by_product(
    product_id: int,
    quality_state: Optional[QualityState] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> list[StockBalanceOut]:
    """Все балансы конкретного продукта по локациям."""
    stmt = (
        select(StockBalance, Section.name, Product.sku)
        .outerjoin(Section, Section.id == StockBalance.location_id)
        .outerjoin(Product, Product.id == StockBalance.product_id)
        .where(StockBalance.product_id == product_id)
    )
    if quality_state is not None:
        stmt = stmt.where(StockBalance.quality_state == quality_state)
    stmt = stmt.order_by(StockBalance.location_id, StockBalance.quality_state)
    result = await db.execute(stmt)
    return await _serialize_balances_with_operations(db, list(result.all()))


# ─── Transactions ─────────────────────────────────────────────────────────────

TX_SORT_FIELDS = frozenset({
    "created_at",
    "reason",
    "quantity",
    "from_location",
    "to_location",
    "quality_state",
    "comment",
})


def _serialize_transaction(
    tx: StockTransaction,
    *,
    from_location_name: str | None = None,
    to_location_name: str | None = None,
) -> StockTransactionOut:
    """ORM → API: Decimal и datetime в строки для стабильной JSON-сериализации."""
    return StockTransactionOut(
        id=tx.id,
        product_id=tx.product_id,
        from_location_id=tx.from_location_id,
        from_location_name=from_location_name,
        to_location_id=tx.to_location_id,
        to_location_name=to_location_name,
        quantity=str(tx.quantity),
        dimensions=tx.dimensions,
        dimensions_label=format_dimensions(tx.dimensions),
        reason=tx.reason,
        from_quality_state=tx.from_quality_state,
        to_quality_state=tx.to_quality_state,
        task_id=tx.task_id,
        transfer_id=tx.transfer_id,
        section_plan_line_id=tx.section_plan_line_id,
        reverses_id=tx.reverses_id,
        source_ref=tx.source_ref,
        idempotency_key=tx.idempotency_key,
        comment=tx.comment,
        created_by=tx.created_by,
        executor_user_id=tx.executor_user_id,
        created_by_user_name=tx.created_by_user_name,
        executor_user_name=tx.executor_user_name,
        performed_at=tx.performed_at.isoformat() if tx.performed_at else None,
        accounted_at=tx.accounted_at.isoformat() if tx.accounted_at else None,
        is_post_factum=tx.is_post_factum,
        created_at=tx.created_at.isoformat() if tx.created_at else None,
    )


@router.get("/transactions", response_model=StockTransactionsListResponse)
async def list_transactions(
    product_id: Optional[int] = Query(default=None),
    transfer_id: Optional[int] = Query(default=None),
    task_id: Optional[int] = Query(default=None),
    reason: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on reason enum value or label",
    ),
    from_location: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on from section name or code",
    ),
    to_location: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on to section name or code",
    ),
    quality_state: Optional[QualityState] = Query(
        default=None,
        description="Column filter: exact match on from/to quality state",
    ),
    comment: Optional[str] = Query(
        default=None,
        description="Column filter: ILIKE on comment",
    ),
    location_id: Optional[int] = Query(
        default=None,
        description="Фильтр по участию локации (from или to)",
    ),
    compensating: Optional[bool] = Query(
        default=None,
        description="True — только компенсации; False — только оригиналы",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Поиск по комментарию, причине, локациям, source_ref",
    ),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> StockTransactionsListResponse:
    """Лента StockTransaction (append-only аудит).

    Поддерживает комбинируемые фильтры и пагинацию. По умолчанию
    последние 50 записей в порядке убывания ``id`` (т.е. новые сверху).
    """
    from_section = aliased(Section)
    to_section = aliased(Section)
    stmt = (
        select(StockTransaction, from_section.name, to_section.name)
        .outerjoin(from_section, from_section.id == StockTransaction.from_location_id)
        .outerjoin(to_section, to_section.id == StockTransaction.to_location_id)
    )
    if product_id is not None:
        stmt = stmt.where(StockTransaction.product_id == product_id)
    if transfer_id is not None:
        stmt = stmt.where(StockTransaction.transfer_id == transfer_id)
    if task_id is not None:
        stmt = stmt.where(StockTransaction.task_id == task_id)
    if reason is not None:
        reason_like = f"%{reason}%"
        stmt = stmt.where(cast(StockTransaction.reason, String).ilike(reason_like))
    if from_location is not None:
        from_location_like = f"%{from_location}%"
        stmt = stmt.where(
            or_(
                from_section.name.ilike(from_location_like),
                from_section.code.ilike(from_location_like),
            )
        )
    if to_location is not None:
        to_location_like = f"%{to_location}%"
        stmt = stmt.where(
            or_(
                to_section.name.ilike(to_location_like),
                to_section.code.ilike(to_location_like),
            )
        )
    if quality_state is not None:
        stmt = stmt.where(
            (StockTransaction.from_quality_state == quality_state)
            | (StockTransaction.to_quality_state == quality_state)
        )
    if comment is not None:
        stmt = stmt.where(StockTransaction.comment.ilike(f"%{comment}%"))
    if location_id is not None:
        stmt = stmt.where(
            (StockTransaction.from_location_id == location_id)
            | (StockTransaction.to_location_id == location_id)
        )
    if compensating is True:
        stmt = stmt.where(StockTransaction.reverses_id.is_not(None))
    elif compensating is False:
        stmt = stmt.where(StockTransaction.reverses_id.is_(None))
    if date_from is not None:
        stmt = stmt.where(
            StockTransaction.created_at >= datetime.combine(date_from, time.min),
        )
    if date_to is not None:
        stmt = stmt.where(
            StockTransaction.created_at <= datetime.combine(date_to, time.max),
        )
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                StockTransaction.comment.ilike(search_like),
                StockTransaction.source_ref.ilike(search_like),
                cast(StockTransaction.reason, String).ilike(search_like),
                from_section.name.ilike(search_like),
                to_section.name.ilike(search_like),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    resolved_sort_by = sort_by if sort_by in TX_SORT_FIELDS else "created_at"
    order_column = StockTransaction.created_at
    if resolved_sort_by == "reason":
        order_column = StockTransaction.reason
    elif resolved_sort_by == "quantity":
        order_column = StockTransaction.quantity
    elif resolved_sort_by == "from_location":
        order_column = from_section.name
    elif resolved_sort_by == "to_location":
        order_column = to_section.name
    elif resolved_sort_by == "quality_state":
        order_column = StockTransaction.to_quality_state
    elif resolved_sort_by == "comment":
        order_column = StockTransaction.comment

    if sort_order == "asc":
        stmt = stmt.order_by(order_column.asc(), StockTransaction.id.asc())
    else:
        stmt = stmt.order_by(order_column.desc(), StockTransaction.id.desc())

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    transactions = [
        _serialize_transaction(
            tx,
            from_location_name=from_name,
            to_location_name=to_name,
        )
        for tx, from_name, to_name in result.all()
    ]
    return StockTransactionsListResponse(
        transactions=transactions,
        total=total,
        limit=limit,
        offset=offset,
    )


# ─── Adjustment (write) ───────────────────────────────────────────────────────


_ADJUSTMENT_REASONS = {Reason.ADJUSTMENT_IN, Reason.ADJUSTMENT_OUT, Reason.MANUAL_IN, Reason.MANUAL_OUT}


@router.post("/adjustment", response_model=StockAdjustmentOut, status_code=201)
async def create_adjustment(
    payload: StockAdjustmentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(list(WRITER_ROLES))),
) -> StockAdjustmentOut:
    """Ручная корректировка остатков (write API).

    Создаёт ``StockTransaction`` через ``StockCommandService.record()``
    с автоматическим определением ``from_/to_location_id`` по направлению
    ``reason``.
    """
    if payload.reason not in _ADJUSTMENT_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"reason must be one of {[r.value for r in _ADJUSTMENT_REASONS]}, got {payload.reason.value}",
        )
    # Журнал действий (#116): ручная корректировка = Action без ref_id.
    action = await action_journal_service.log(
        db,
        action_type="manual_adjustment",
        ref_id=None,
        actor=user.full_name or user.username,
    )

    if payload.reason in (Reason.ADJUSTMENT_IN, Reason.MANUAL_IN):
        from_location_id = None
        to_location_id = payload.location_id
    else:
        from_location_id = payload.location_id
        to_location_id = None

    cmd = StockCommand(
        product_id=payload.product_id,
        quantity=payload.quantity,
        reason=payload.reason,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        dimensions=payload.dimensions,
        quality_state=payload.quality_state,
        comment=payload.comment,
        created_by=user.id,
        created_by_user_name=user.full_name or user.username,
        action_id=action.id,
    )
    service = StockCommandService()
    try:
        tx = await service.record(db, cmd)
    except StockValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()

    return StockAdjustmentOut(
        id=tx.id,
        reason=tx.reason,
        quantity=str(tx.quantity),
        created_at=tx.created_at.isoformat() if tx.created_at else None,
    )


# ─── Remainders Import ─────────────────────────────────────────────────────────


def _location_or_404(location_id: int, db: AsyncSession) -> None:
    """Check location exists, used as a dependency."""
    # This is a placeholder — actual validation is done inline in each endpoint.


@router.get("/import/remainders/template")
async def download_remainders_template(
    location_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Скачать Excel-шаблон для импорта остатков на указанную локацию."""
    try:
        template_bytes = await generate_remainders_template_for_location(db, location_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    filename = f"import_remainders_template_{location_id}.xlsx"
    # Encode filename for Content-Disposition (RFC 5987)
    encoded_name = filename.encode("utf-8")
    return StreamingResponse(
        BytesIO(template_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name.decode('latin-1')}",
        },
    )


@router.get("/import/remainders/operations", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def get_remainder_import_operations(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Справочник значимых производственных операций для UI импорта остатков.

    Возвращает список в формате ``RouteStepsDisplay``:
    ``[{sequence, section_code, section_name, section_icon, section_icon_color,
    operation_code, operation_name, op_icon, op_icon_color, is_significant}]``.
    """
    return await resolve_operations_dictionary(db)


def _parse_remainder_override_json(
    raw: str | None,
    *,
    field_name: str,
    value_parser,
) -> dict[int, object] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
        return {int(k): value_parser(v) for k, v in parsed.items()}
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name} JSON: {exc}",
        ) from exc


async def _load_section_names(
    db: AsyncSession,
    section_ids: set[int],
) -> dict[int, str]:
    if not section_ids:
        return {}
    result = await db.execute(
        select(Section.id, Section.name).where(Section.id.in_(section_ids))
    )
    return {row.id: row.name for row in result.all()}


@router.post(
    "/import/remainders/preview",
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def preview_remainders_excel(
    location_id: int | None = Form(None),
    quality_state: QualityState = Form(QualityState.GOOD),
    target_section_overrides: str | None = Form(None),
    quality_state_overrides: str | None = Form(None),
    sheet_index: int = Form(0),
    row_selection: str | None = Form(None),
    template_id: int | None = Form(None),
    search: str | None = Form(None),
    filter_status: str = Form("all"),
    sort_by: str = Form("row"),
    sort_order: str = Form("asc"),
    limit: int = Form(50),
    offset: int = Form(0),
    row: str | None = Form(None),
    sku: str | None = Form(None),
    quantity: str | None = Form(None),
    length: str | None = Form(None),
    operations: str | None = Form(None),
    quality: str | None = Form(None),
    section: str | None = Form(None),
    errors: str | None = Form(None),
    file: UploadFile | None = File(None),
    clipboard_text: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Парсит Excel или буфер обмена и возвращает preview с валидацией, БЕЗ записи в БД.

    * ``location_id`` опционален; если передан — проверяется на существование.
    * ``quality_state`` — значение по умолчанию для строк без колонки «Статус качества».
    * ``target_section_overrides`` — опциональный JSON ``{"row_num": sec_id, ...}``
      для UI-оверрайда участка.
    * ``clipboard_text`` — TSV из буфера (копия из Excel), альтернатива ``file``.
    * ``limit`` / ``offset`` / ``items_total`` — серверная пагинация по ``items``.
    * ``search`` — поиск по SKU, product_name, номеру строки.
    * ``filter_status`` — ``all`` или ``invalid``.
    * ``sort_by`` / ``sort_order`` — сортировка страницы preview.
    * ``row``, ``sku``, ``quantity``, ``length``, ``operations``, ``quality``,
      ``section``, ``errors`` — column filters (partial match).
    """
    if location_id is not None:
        location = await db.get(Section, location_id)
        if location is None:
            raise HTTPException(status_code=404, detail=f"Location id={location_id} not found")

    if filter_status not in {"all", "invalid"}:
        raise HTTPException(status_code=422, detail="filter_status must be 'all' or 'invalid'")

    parsed_target_overrides = _parse_remainder_override_json(
        target_section_overrides,
        field_name="target_section_overrides",
        value_parser=int,
    )
    parsed_quality_overrides = _parse_remainder_override_json(
        quality_state_overrides,
        field_name="quality_state_overrides",
        value_parser=lambda value: QualityState(str(value).lower()),
    )

    sheet_name, total_rows, items, summary = await _parse_remainder_import_source(
        file=file,
        clipboard_text=clipboard_text,
        sheet_index=sheet_index,
        row_selection=row_selection,
        column_mapping=await _load_template_column_mapping(db, template_id),
    )

    # Enrich items with product info
    await _lookup_remainder_products(db, items)

    # Габариты: явная длина / типовой размер / invalid (ADR-0003, п. 3)
    await resolve_remainder_dimensions(db, items)

    # Resolve completed stages and target sections
    ops_dict = await resolve_operations_dictionary(db)
    for item in items:
        if item.completed_operations_raw:
            item.completed_stages = await resolve_completed_stages(
                db, item.completed_operations_raw, ops_dict, item.errors,
            )
        if item.target_section_name:
            sec_id, _ = await resolve_target_section(
                db, item.target_section_name, item.errors,
            )
            item.target_section_id = sec_id

    # Recalculate summary after product enrichment
    valid_count = sum(1 for it in items if it.status == "valid")
    invalid_count = sum(1 for it in items if it.status == "invalid")
    quantity_total = sum(
        (it.quantity or 0) for it in items if it.status == "valid"
    )

    section_ids: set[int] = set()
    if parsed_target_overrides:
        section_ids.update(parsed_target_overrides.values())
    for item in items:
        if item.target_section_id is not None:
            section_ids.add(item.target_section_id)
    section_names = await _load_section_names(db, section_ids)

    preview_page = query_remainder_preview_items(
        items,
        search=search,
        filter_status=filter_status,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
        default_quality_state=quality_state,
        target_section_overrides=parsed_target_overrides,
        quality_state_overrides=parsed_quality_overrides,
        section_names=section_names,
        row=row,
        sku=sku,
        quantity=quantity,
        length=length,
        operations=operations,
        quality=quality,
        section=section,
        errors=errors,
    )

    return {
        "sheet_name": sheet_name,
        "total_rows": total_rows,
        "summary": {
            "total": len(items),
            "valid": valid_count,
            "invalid": invalid_count,
            "quantity_total": round(quantity_total, 3),
        },
        "section_meta": [
            {
                "source_row_number": meta.source_row_number,
                "status": meta.status,
                "target_section_id": meta.target_section_id,
                "target_section_name": meta.target_section_name,
            }
            for meta in preview_page.section_meta
        ],
        "items": [item.__dict__ for item in preview_page.items],
        "items_total": preview_page.items_total,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }


@router.post(
    "/import/remainders",
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def import_remainders_excel(
    location_id: int = Form(...),
    quality_state: QualityState = Form(QualityState.GOOD),
    target_section_overrides: str | None = Form(None),
    quality_state_overrides: str | None = Form(None),
    sheet_index: int = Form(0),
    row_selection: str | None = Form(None),
    template_id: int | None = Form(None),
    skip_invalid: bool = Form(True),
    clear_existing: bool = Form(False),
    file: UploadFile | None = File(None),
    clipboard_text: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Применить импорт остатков: создать ``MANUAL_IN`` транзакции.

    Параметры:
    * ``location_id`` — участок (склад).
    * ``quality_state`` — статус качества по умолчанию для пустых ячеек.
    * ``quality_state_overrides`` — опциональный JSON ``{"row_num": "scrap", ...}``.
    * ``target_section_overrides`` — опциональный JSON ``{"row_num": sec_id, ...}``
      для построчного оверрайда участка.
    * ``file`` — .xlsx файл с колонками SKU | Количество | Комментарий.
    * ``clipboard_text`` — TSV из буфера, альтернатива ``file``.
    * ``sheet_index`` — индекс листа (0=первый).
    * ``row_selection`` — опциональный фильтр строк, ``"2-10,12"``.
    * ``skip_invalid`` — пропускать строки с ошибками (True) или
      откатывать весь импорт (False).
    * ``clear_existing`` — обнулить текущие остатки по
      ``(location_id, quality_state)`` перед импортом.
    """
    # Parse target_section_overrides JSON (if provided)
    parsed_overrides: dict[int, int] | None = None
    if target_section_overrides is not None:
        try:
            raw = json.loads(target_section_overrides)
            parsed_overrides = {int(k): int(v) for k, v in raw.items()}
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid target_section_overrides JSON: {exc}",
            )

    parsed_quality_overrides: dict[int, QualityState] | None = None
    if quality_state_overrides is not None:
        try:
            raw_quality = json.loads(quality_state_overrides)
            parsed_quality_overrides = {
                int(k): QualityState(str(v).lower())
                for k, v in raw_quality.items()
            }
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid quality_state_overrides JSON: {exc}",
            )

    # clear_existing + target_section_overrides is forbidden
    if clear_existing and target_section_overrides is not None:
        raise HTTPException(
            status_code=422,
            detail="clear_existing не поддерживается при построчном указании участков",
        )

    # Validate location
    location = await db.get(Section, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Location id={location_id} not found")

    _sheet_name, _total_rows, items, _summary = await _parse_remainder_import_source(
        file=file,
        clipboard_text=clipboard_text,
        sheet_index=sheet_index,
        row_selection=row_selection,
        column_mapping=await _load_template_column_mapping(db, template_id),
    )

    # Resolve completed stages and target sections before import
    ops_dict = await resolve_operations_dictionary(db)
    for item in items:
        if item.completed_operations_raw:
            item.completed_stages = await resolve_completed_stages(
                db, item.completed_operations_raw, ops_dict, item.errors,
            )
        if item.target_section_name:
            sec_id, _ = await resolve_target_section(
                db, item.target_section_name, item.errors,
            )
            item.target_section_id = sec_id

    # If nothing to import
    if not items:
        return {
            "success": True,
            "imported_count": 0,
            "errors": [],
            "transaction_ids": [],
        }

    result: ImportResult = await apply_remainders_import(
        db=db,
        location_id=location_id,
        items=items,
        quality_state=quality_state,
        user=user,
        clear_existing=clear_existing,
        skip_invalid=skip_invalid,
        target_section_overrides=parsed_overrides,
        quality_state_overrides=parsed_quality_overrides,
    )

    return {
        "success": result.success,
        "imported_count": result.imported_count,
        "errors": result.errors,
        "transaction_ids": result.transaction_ids,
    }
