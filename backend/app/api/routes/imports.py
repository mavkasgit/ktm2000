import json
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.import_template import ImportTemplate
from app.models.imports import ImportBatch, ImportBatchMode, ImportBatchStatus, ImportFile
from app.models.production_plan import PlanChangeSet, ProductionPlan
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
    sheet_index: int = Form(0),
    mode: ImportBatchMode = Form(ImportBatchMode.create_plan),
    production_plan_id: int | None = Form(None),
    template_id: int | None = Query(None),
    column_mapping: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewOut:
    resolved_mapping = None
    if template_id is not None:
        template = await db.get(ImportTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        resolved_mapping = dict(template.column_mapping)
    if column_mapping is not None:
        try:
            parsed_mapping = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid column_mapping JSON: {exc}") from exc
        if not isinstance(parsed_mapping, dict):
            raise HTTPException(status_code=400, detail="column_mapping must be a JSON object")
        resolved_mapping = {**(resolved_mapping or {}), **parsed_mapping}

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
            column_mapping=resolved_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ImportPreviewOut(**result)


def _test_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(
        [
            "Артикул",
            "пополнение",
            "Наименование",
            "остатки сырья на КТМ",
            "Цвет",
            "кол-во шт. в 2,7",
            "Длина, м",
            "Пробивка/сверловка",
            "Упаковка",
            "Примечание ",
            "Длина после упак, м",
            "кол-во штук готовой продукции",
            "Запад",
            "Восток",
            "Вид конечного продукта",
            "Комментарии",
        ]
    )
    ws.append(
        [
            "ЮП-2630",
            "ТЗ",
            "Стык с дюбелем 40мм 2,7 анод.серебро матовый",
            3400,
            "серебро",
            100,
            2.7,
            "",
            "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт",
            "",
            2.7,
            100,
            100,
            100,
            "ГП",
            "",
        ]
    )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@router.post("/excel/test", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def import_test_excel(
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewOut:
    content = _test_workbook()
    try:
        result = await create_excel_import_change_set(
            db,
            filename="test-yup2630.xlsx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sheet_index=0,
            mode=ImportBatchMode.create_plan,
            production_plan_id=None,
            column_mapping=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ImportPreviewOut(**result)


class ImportRecentOut(BaseModel):
    id: int
    production_plan_id: int
    change_set_id: int | None
    plan_name: str
    plan_no: str
    original_filename: str
    mode: str
    status: str
    sheet_name: str
    parsed_rows: int
    total_rows: int
    error_count: int
    warning_count: int
    summary: dict
    created_at: str

    class Config:
        from_attributes = True


@router.get("/recent", response_model=list[ImportRecentOut])
async def list_recent_imports(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[ImportRecentOut]:
    result = await db.execute(
        select(ImportBatch, ProductionPlan, ImportFile, PlanChangeSet)
        .join(ProductionPlan, ImportBatch.production_plan_id == ProductionPlan.id)
        .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
        .outerjoin(PlanChangeSet, PlanChangeSet.import_batch_id == ImportBatch.id)
        .order_by(desc(ImportBatch.created_at))
        .limit(limit)
    )
    items = []
    for batch, plan, file, change_set in result.all():
        summary = batch.summary or {}
        items.append(
            ImportRecentOut(
                id=batch.id,
                production_plan_id=batch.production_plan_id,
                change_set_id=change_set.id if change_set else None,
                plan_name=plan.name,
                plan_no=plan.plan_no,
                original_filename=file.original_filename,
                mode=batch.mode.value,
                status=batch.status.value,
                sheet_name=batch.sheet_name,
                parsed_rows=batch.parsed_rows,
                total_rows=batch.total_rows,
                error_count=summary.get("error_count", 0),
                warning_count=summary.get("warning_count", 0),
                summary=summary,
                created_at=batch.created_at.isoformat() if batch.created_at else "",
            )
        )
    return items
