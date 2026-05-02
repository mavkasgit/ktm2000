from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.imports import ImportBatchMode
from app.services.plan_import_service import create_excel_import_change_set

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportPreviewOut(BaseModel):
    import_file_id: int
    import_batch_id: int
    production_plan_id: int
    change_set_id: int
    sheet_name: str
    header_row_number: int
    summary: dict
    items: list[dict]


@router.post("/excel", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def import_excel_plan(
    file: UploadFile = File(...),
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewOut:
    content = await file.read()
    try:
        result = await create_excel_import_change_set(
            db,
            filename=file.filename or "workbook.xls",
            content=content,
            content_type=file.content_type,
            sheet_index=sheet_index,
            mode=mode,
            production_plan_id=production_plan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ImportPreviewOut(**result)
