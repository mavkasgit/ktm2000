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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, require_role
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
    quality_state: QualityState = QualityState.good
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


_ADJUSTMENT_REASONS = {Reason.adjustment_in, Reason.adjustment_out, Reason.manual_in, Reason.manual_out}


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

    if payload.reason in (Reason.adjustment_in, Reason.manual_in):
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
