"""FastAPI router for the Stock Ledger (v2).

Mounted at ``/api/v2/stock``. Read-only endpoints для сверки и будущего
UI-перехода (Этап 6). Старый ``/api/spg/*`` остаётся live до Этапа 7 —
никаких ``if legacy`` флагов, версии живут параллельно.

Endpoints:

  * ``GET /v2/stock/balance``             — список строк StockBalance
    с опциональными фильтрами ``product_id`` / ``location_id`` /
    ``quality_state``.
  * ``GET /v2/stock/balance/by-product/{product_id}`` — все балансы
    конкретного продукта по локациям.
  * ``GET /v2/stock/transactions``        — лента StockTransaction с
    фильтрами ``product_id`` / ``transfer_id`` / ``task_id`` / ``reason``
    и пагинацией ``limit`` / ``offset``.

Все эндпоинты требуют только reader-роль: это аудит/сверка, не мутация.
Запись идёт исключительно через сервисы доменов (transfer_send и т.д.),
прямого write-API здесь нет — см. принцип «единственный путь записи» в
``app/stock/services.py::StockCommandService``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.product import Product
from app.models.section import Section
from app.models.user import User
from app.stock.models import (
    QualityState,
    Reason,
    StockBalance,
    StockTransaction,
)
from app.stock.services import StockCommand, StockCommandService
from app.stock.import_service import (
    ImportResult,
    RemainderItem,
    SheetSummary,
    apply_remainders_import,
    generate_remainders_template_for_location,
    parse_remainders_excel,
)
from app.stock.import_service import _lookup_products as _lookup_remainder_products
from fastapi.responses import StreamingResponse
from io import BytesIO

router = APIRouter(prefix="/v2/stock", tags=["stock-ledger"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class StockBalanceOut(BaseModel):
    id: int
    product_id: int
    location_id: int
    location_name: str | None = None
    quality_state: QualityState
    balance_qty: str  # Decimal → str для стабильной сериализации
    refreshed_at: str | None = None

    class Config:
        from_attributes = True


class StockTransactionOut(BaseModel):
    id: int
    product_id: int
    from_location_id: int | None
    to_location_id: int | None
    quantity: str
    reason: Reason
    from_quality_state: QualityState
    to_quality_state: QualityState
    task_id: int | None
    transfer_id: int | None
    section_plan_line_id: int | None
    compensates_tx_id: int | None
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
    """Payload для ручной корректировки остатков (POST /v2/stock/adjustment).

    ``reason`` определяет направление движения:
    * ``adjustment_in`` / ``manual_in`` — приход на ``location_id`` (to_location)
    * ``adjustment_out`` / ``manual_out`` — расход с ``location_id`` (from_location)
    """
    product_id: int
    location_id: int
    quantity: float = Field(gt=0)
    reason: Reason
    quality_state: QualityState = QualityState.GOOD
    comment: str | None = None


class StockAdjustmentOut(BaseModel):
    id: int
    reason: Reason
    quantity: str
    created_at: str | None = None


# ─── Balance ──────────────────────────────────────────────────────────────────


def _serialize_balance(row: StockBalance, location_name: str | None) -> StockBalanceOut:
    return StockBalanceOut(
        id=row.id,
        product_id=row.product_id,
        location_id=row.location_id,
        location_name=location_name,
        quality_state=row.quality_state,
        balance_qty=str(row.balance_qty),
        refreshed_at=row.refreshed_at.isoformat() if row.refreshed_at else None,
    )


@router.get("/balance", response_model=list[StockBalanceOut])
async def list_balances(
    product_id: Optional[int] = Query(default=None),
    location_id: Optional[int] = Query(default=None),
    quality_state: Optional[QualityState] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> list[StockBalanceOut]:
    """Список строк баланса (projection из StockTransaction).

    Без фильтров возвращает все ненулевые строки. Баланс = SUM(in) - SUM(out)
    по ключу ``(product, location, quality_state)``; нулевые строки не
    хранятся (см. ``StockProjectionManager.refresh_balance``).
    """
    stmt = select(StockBalance, Section.name).outerjoin(
        Section, Section.id == StockBalance.location_id
    )
    if product_id is not None:
        stmt = stmt.where(StockBalance.product_id == product_id)
    if location_id is not None:
        stmt = stmt.where(StockBalance.location_id == location_id)
    if quality_state is not None:
        stmt = stmt.where(StockBalance.quality_state == quality_state)
    stmt = stmt.order_by(StockBalance.product_id, StockBalance.location_id)
    result = await db.execute(stmt)
    return [
        _serialize_balance(row, name) for row, name in result.all()
    ]


@router.get("/balance/by-product/{product_id}", response_model=list[StockBalanceOut])
async def list_balances_by_product(
    product_id: int,
    quality_state: Optional[QualityState] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> list[StockBalanceOut]:
    """Все балансы конкретного продукта по локациям."""
    stmt = select(StockBalance, Section.name).outerjoin(
        Section, Section.id == StockBalance.location_id
    ).where(StockBalance.product_id == product_id)
    if quality_state is not None:
        stmt = stmt.where(StockBalance.quality_state == quality_state)
    stmt = stmt.order_by(StockBalance.location_id, StockBalance.quality_state)
    result = await db.execute(stmt)
    return [_serialize_balance(row, name) for row, name in result.all()]


# ─── Transactions ─────────────────────────────────────────────────────────────


@router.get("/transactions", response_model=list[StockTransactionOut])
async def list_transactions(
    product_id: Optional[int] = Query(default=None),
    transfer_id: Optional[int] = Query(default=None),
    task_id: Optional[int] = Query(default=None),
    reason: Optional[Reason] = Query(default=None),
    location_id: Optional[int] = Query(
        default=None,
        description="Фильтр по участию локации (from или to)",
    ),
    compensating: Optional[bool] = Query(
        default=None,
        description="True — только компенсации; False — только оригиналы",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role(READER_ROLES)),
) -> list[StockTransactionOut]:
    """Лента StockTransaction (append-only аудит).

    Поддерживает комбинируемые фильтры и пагинацию. По умолчанию
    последние 100 записей в порядке убывания ``id`` (т.е. новые сверху).
    """
    stmt = select(StockTransaction)
    if product_id is not None:
        stmt = stmt.where(StockTransaction.product_id == product_id)
    if transfer_id is not None:
        stmt = stmt.where(StockTransaction.transfer_id == transfer_id)
    if task_id is not None:
        stmt = stmt.where(StockTransaction.task_id == task_id)
    if reason is not None:
        stmt = stmt.where(StockTransaction.reason == reason)
    if location_id is not None:
        stmt = stmt.where(
            (StockTransaction.from_location_id == location_id)
            | (StockTransaction.to_location_id == location_id)
        )
    if compensating is True:
        stmt = stmt.where(StockTransaction.compensates_tx_id.is_not(None))
    elif compensating is False:
        stmt = stmt.where(StockTransaction.compensates_tx_id.is_(None))
    stmt = stmt.order_by(StockTransaction.id.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return [StockTransactionOut.model_validate(t) for t in result.scalars().all()]


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
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"reason must be one of {[r.value for r in _ADJUSTMENT_REASONS]}, got {payload.reason.value}",
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
        quality_state=payload.quality_state,
        comment=payload.comment,
        created_by=user.id,
        created_by_user_name=user.full_name or user.username,
    )
    service = StockCommandService()
    tx = await service.record(db, cmd)
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


@router.post(
    "/import/remainders/preview",
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def preview_remainders_excel(
    file: UploadFile = File(...),
    location_id: int = Form(...),
    quality_state: QualityState = Form(QualityState.GOOD),
    sheet_index: int = Form(0),
    row_selection: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Парсит Excel и возвращает preview с валидацией, БЕЗ записи в БД.

    * ``location_id`` проверяется на существование.
    * ``quality_state`` пока не влияет на preview, но передаётся для
      единообразия с POST /import/remainders.
    """
    # Validate location
    location = await db.get(Section, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Location id={location_id} not found")

    content = await file.read()

    try:
        sheet_name, total_rows, items, summary = await parse_remainders_excel(
            content, sheet_index, row_selection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Enrich items with product info
    await _lookup_remainder_products(db, items)

    # Recalculate summary after product enrichment
    valid_count = sum(1 for it in items if it.status == "valid")
    invalid_count = sum(1 for it in items if it.status == "invalid")
    quantity_total = sum(
        (it.quantity or 0) for it in items if it.status == "valid"
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
        "items": [item.__dict__ for item in items],
    }


@router.post(
    "/import/remainders",
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def import_remainders_excel(
    file: UploadFile = File(...),
    location_id: int = Form(...),
    quality_state: QualityState = Form(QualityState.GOOD),
    sheet_index: int = Form(0),
    row_selection: str | None = Form(None),
    skip_invalid: bool = Form(True),
    clear_existing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Применить импорт остатков: создать ``MANUAL_IN`` транзакции.

    Параметры:
    * ``location_id`` — целевая секция (склад / участок).
    * ``quality_state`` — состояние качества (по умолч. GOOD).
    * ``file`` — .xlsx файл с колонками SKU | Количество | Комментарий.
    * ``sheet_index`` — индекс листа (0=первый).
    * ``row_selection`` — опциональный фильтр строк, ``"2-10,12"``.
    * ``skip_invalid`` — пропускать строки с ошибками (True) или
      откатывать весь импорт (False).
    * ``clear_existing`` — обнулить текущие остатки по
      ``(location_id, quality_state)`` перед импортом.
    """
    # Validate location
    location = await db.get(Section, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail=f"Location id={location_id} not found")

    content = await file.read()

    try:
        _sheet_name, _total_rows, items, _summary = await parse_remainders_excel(
            content, sheet_index, row_selection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
    )

    return {
        "success": result.success,
        "imported_count": result.imported_count,
        "errors": result.errors,
        "transaction_ids": result.transaction_ids,
    }
