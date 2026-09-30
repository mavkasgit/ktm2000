"""REST-роуты истории импорта остатков (ADR-0052, ADR-0053).

Префикс ``/stock/import`` — рядом с существующими ``/stock/import/remainders``,
история импорта остатков и есть продолжение этого эндпоинта.

Права (ADR-0052 п.6): **читать** историю может любая роль из
``READER_ROLES`` — это факт учёта, а не изменение; **откатывать** и
**скрывать** — только ``admin``. Откат идёт через тот же
``reversal_service``, что и откат из общего журнала, поэтому
``CoverageShortfall`` и ``StalePlanToken`` ведут себя одинаково; правило
«только последний импорт склада» обеспечивает компенсатор
(``import_batch_rollback_blockers``), а не этот роут.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.imports import ImportFile
from app.models.user import User, UserRole
from app.reversal import errors
from app.reversal.service import reversal_service
from app.stock import import_history as history
from app.stock.import_history import ImportHistoryError

router = APIRouter(prefix="/stock/import", tags=["stock-import-history"])


class ImportBatchOut(BaseModel):
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
    created_at: str
    created_by_name: str | None
    rolled_back_at: str | None
    deleted_at: str | None
    can_rollback: bool
    rollback_blocked_reason: str | None


class ImportRowOut(BaseModel):
    """Строка импорта в диалоге «посмотреть»."""

    row_id: int
    source_row_number: int
    sku: str
    matched_sku: str | None
    product_id: int | None
    product_sku: str | None
    product_name: str | None
    quantity: str | None
    dimensions_label: str
    target_section_id: int | None
    target_section_name: str | None
    quality_state: str | None
    status: str
    errors: list[str]
    warnings: list[str]
    raw_values: list[str]
    current_balance: str | None


class ImportBatchDetailOut(BaseModel):
    """Батч + его строки одним ответом — «посмотреть» открывается одним запросом."""

    batch: ImportBatchOut
    rows: list[ImportRowOut]


class RollbackIn(BaseModel):
    plan_token: str
    reason: str | None = None


class HideIn(BaseModel):
    reason: str | None = None


def _batch_out(view: history.BatchView) -> ImportBatchOut:
    return ImportBatchOut(
        batch_id=view.batch_id,
        action_id=view.action_id,
        status=view.status,
        legacy=view.legacy,
        clear_existing=view.clear_existing,
        filename=view.filename,
        file_id=view.file_id,
        sheet_name=view.sheet_name,
        location_id=view.location_id,
        location_name=view.location_name,
        total_rows=view.total_rows,
        imported_rows=view.imported_rows,
        skipped_rows=view.skipped_rows,
        created_at=view.created_at.isoformat(),
        created_by_name=view.created_by_name,
        rolled_back_at=view.rolled_back_at.isoformat() if view.rolled_back_at else None,
        deleted_at=view.deleted_at.isoformat() if view.deleted_at else None,
        can_rollback=view.can_rollback,
        rollback_blocked_reason=view.rollback_blocked_reason,
    )


def _row_out(view: history.RowView) -> ImportRowOut:
    return ImportRowOut(
        row_id=view.row_id,
        source_row_number=view.source_row_number,
        sku=view.sku,
        matched_sku=view.matched_sku,
        product_id=view.product_id,
        product_sku=view.product_sku,
        product_name=view.product_name,
        quantity=str(view.quantity) if view.quantity is not None else None,
        dimensions_label=view.dimensions_label,
        target_section_id=view.target_section_id,
        target_section_name=view.target_section_name,
        quality_state=view.quality_state,
        status=view.status,
        errors=view.errors,
        warnings=view.warnings,
        raw_values=view.raw_values,
        current_balance=(
            str(view.current_balance) if view.current_balance is not None else None
        ),
    )


def _history_error(exc: ImportHistoryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "error": str(exc)}
    )


@router.get(
    "/remainders/batches",
    response_model=list[ImportBatchOut],
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def list_import_batches(
    location_id: int | None = Query(default=None),
    include_hidden: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[ImportBatchOut]:
    """История импортов остатков, новые сверху (ADR-0052 п.1).

    ``location_id`` — фильтр по складу; ``include_hidden`` показывает и
    мягко удалённые записи (ADR-0052 п.5).
    """
    views = await history.list_batches(
        db, location_id=location_id, include_hidden=include_hidden
    )
    return [_batch_out(v) for v in views]


@router.get(
    "/remainders/batches/{batch_id}",
    response_model=ImportBatchDetailOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def get_import_batch(
    batch_id: int, db: AsyncSession = Depends(get_db)
) -> ImportBatchDetailOut:
    """Батч и его строки — «посмотреть» (ADR-0052 п.8, Q23).

    У откатанного батча строки те же, а ``current_balance`` показывает, что
    осталось на складе сейчас; UI обязан показать плашку «откатан».
    """
    try:
        batch = await history.get_batch(db, batch_id)
        rows = await history.get_batch_rows(db, batch_id)
    except ImportHistoryError as exc:
        raise _history_error(exc) from exc
    views = await history.list_batches(
        db, include_hidden=True, location_id=batch.location_id
    )
    view = next((v for v in views if v.batch_id == batch_id), None)
    if view is None:  # pragma: no cover - батч прочитан, но не попал в выборку
        raise HTTPException(status_code=404, detail="Import batch not found")
    return ImportBatchDetailOut(
        batch=_batch_out(view), rows=[_row_out(r) for r in rows]
    )


@router.get(
    "/remainders/batches/{batch_id}/file",
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def download_import_batch_file(
    batch_id: int, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    """Исходный файл батча — «Скачать» (ADR-0052 п.9).

    У legacy-батчей и загрузок из буфера файла нет: 404 с внятным кодом,
    чтобы UI отключил кнопку, а не ловил 404 при клике.
    """
    try:
        batch = await history.get_batch(db, batch_id)
    except ImportHistoryError as exc:
        raise _history_error(exc) from exc
    if batch.file_id is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "batch_file_missing",
                "error": "У этого импорта файл не сохранился",
            },
        )
    file = await db.get(ImportFile, batch.file_id)
    if file is None or not file.stored_path:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "batch_file_missing",
                "error": "Файл импорта отсутствует в хранилище",
            },
        )
    return FileResponse(
        file.stored_path,
        filename=file.original_filename,
        media_type=file.content_type or "application/octet-stream",
    )


@router.post(
    "/remainders/batches/{batch_id}/rollback",
    dependencies=[Depends(require_role([UserRole.admin]))],
)
async def rollback_import_batch(
    batch_id: int,
    payload: RollbackIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Откатить батч зеркальными компенсациями (ADR-0052 п.3).

    Только ``admin`` (ADR-0052 п.6). Компенсируются **обе** фазы батча —
    гашение ``clear_existing`` и заливку — поэтому остаток возвращается к
    состоянию до импорта, а не обнуляется.
    """
    try:
        batch = await history.get_batch(db, batch_id)
        await history.assert_rollback_allowed(db, batch)
    except ImportHistoryError as exc:
        raise _history_error(exc) from exc

    try:
        result = await reversal_service.reverse(
            db,
            batch.action_id,
            plan_token=payload.plan_token,
            reason=payload.reason,
            actor=getattr(current_user, "full_name", None)
            or getattr(current_user, "username", None)
            or "system",
            actor_id=getattr(current_user, "id", None),
        )
    except errors.AlreadyReversed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except errors.HasDependentActions as exc:
        raise HTTPException(
            status_code=409, detail={"error": str(exc), "chain": exc.chain}
        ) from exc
    except errors.CoverageShortfall as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": (
                    "Недостаточно покрытия: часть материала после импорта "
                    "израсходована, откат сделает остаток отрицательным"
                ),
                "node": exc.node,
                "deficit": str(exc.deficit),
            },
        ) from exc
    except errors.StalePlanToken as exc:
        raise HTTPException(
            status_code=409, detail="Мир изменился с момента предпросмотра"
        ) from exc
    except errors.NotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await history.mark_rolled_back(db, batch, user=current_user)
    return {
        "rolled_back": True,
        "batch_id": batch_id,
        "action_id": batch.action_id,
        "reversal_action_id": result.reversal_action_id,
        "compensated_tx_ids": list(result.compensated_tx_ids),
    }


@router.post(
    "/remainders/batches/{batch_id}/hide",
    dependencies=[Depends(require_role([UserRole.admin]))],
)
async def hide_import_batch(
    batch_id: int,
    payload: HideIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Мягко убрать батч из списка (ADR-0052 п.5).

    Ledger не трогается: проводки остаются, узел журнала по ADR-0019 §7 не
    удаляется никогда. Это «не хочу это видеть», а не «отменить» — отмена
    живёт в ``/rollback``.
    """
    try:
        await history.hide_batch(
            db, batch_id, user=current_user, reason=payload.reason if payload else None
        )
    except ImportHistoryError as exc:
        raise _history_error(exc) from exc
    return {"hidden": True, "batch_id": batch_id}
