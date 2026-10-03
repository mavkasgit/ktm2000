import asyncio
import json
from io import BytesIO
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PLAN_OWNER_ROLES, READER_ROLES, require_role
from app.core.database import get_db
from app.models.import_template import ImportTemplate
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.product import Product
from app.models.production_plan import (
    PlanChangeSet,
    PlanPosition,
    ProductionPlan,
    require_current_length_model,
)
from app.models.route import RouteRuleProfile
from app.models.user import User
from app.services.plan_import_service import create_excel_import_change_set
from app.services.position_route_batch import resolve_position_routes_batch

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportPreviewOut(BaseModel):
    import_file_id: int
    import_batch_id: int
    production_plan_id: int
    change_set_id: int
    template_id: int | None = None
    rule_profile_id: int | None = None
    rules_snapshot: list[dict] = Field(default_factory=list)
    route_selection_diagnostics: dict = Field(default_factory=dict)
    sheet_name: str
    header_row_number: int
    summary: dict
    items: list[dict]
    quantity_adjusted_total: str | None = None


async def _resolve_template_context(
    db: AsyncSession,
    template_id: int,
    column_mapping: str | None,
) -> tuple[dict | None, int | None]:
    """Резолв шаблона импорта: маппинг колонок + профиль правил маршрута.

    Общий шаг upload-импорта (`/excel`) и бесфайловой симуляции
    (`/excel/simulate`) — иначе конвенция разъехалась бы на две.
    """
    template = await db.get(ImportTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    if not template.is_active:
        raise HTTPException(status_code=400, detail="Шаблон неактивен")

    resolved_mapping: dict | None = dict(template.column_mapping)
    rule_profile_id = (
        await db.execute(
            select(RouteRuleProfile.id)
            .where(RouteRuleProfile.import_template_id == template_id)
            .order_by(desc(RouteRuleProfile.is_active), desc(RouteRuleProfile.priority), RouteRuleProfile.id.asc())
            .limit(1)
        )
    ).scalars().first()
    if column_mapping is not None:
        try:
            parsed_mapping = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Некорректный JSON в column_mapping: {exc}") from exc
        if not isinstance(parsed_mapping, dict):
            raise HTTPException(status_code=400, detail="Поле column_mapping должно быть JSON-объектом")
        resolved_mapping = {**(resolved_mapping or {}), **parsed_mapping}
    return resolved_mapping, rule_profile_id


async def _reject_legacy_plan_mutation(
    db: AsyncSession,
    production_plan_id: int | None,
) -> None:
    if production_plan_id is None:
        return
    plan = await db.get(ProductionPlan, production_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Производственный план не найден")
    try:
        require_current_length_model(plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/excel", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def import_excel_plan(
    file: UploadFile = File(...),
    sheet_index: int = Form(0),
    mode: ImportBatchMode = Form(ImportBatchMode.create_plan),
    production_plan_id: int | None = Form(None),
    row_selection: str | None = Form(None),
    template_id: int | None = Query(None),
    column_mapping: str | None = Query(None),
    normalize_hanger_quantity: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(list(PLAN_OWNER_ROLES))),
) -> ImportPreviewOut:
    if template_id is None:
        raise HTTPException(status_code=400, detail="Поле template_id обязательно")
    await _reject_legacy_plan_mutation(db, production_plan_id)
    resolved_mapping, rule_profile_id = await _resolve_template_context(
        db, template_id, column_mapping
    )

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
            row_selection=row_selection,
            template_id=template_id,
            rule_profile_id=rule_profile_id,
            normalize_hanger_quantity=normalize_hanger_quantity,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ImportPreviewOut(**result)


class SheetListOut(BaseModel):
    sheets: list[str]


@router.post(
    "/excel/sheets",
    response_model=SheetListOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def list_excel_sheets(file: UploadFile = File(...)) -> SheetListOut:
    from io import BytesIO

    from app.services.excel_import import validate_excel_extension

    validate_excel_extension(file.filename or "")
    content = await file.read()
    from python_calamine import load_workbook

    workbook = load_workbook(BytesIO(content))
    return SheetListOut(sheets=workbook.sheet_names)


class SheetPreviewOut(BaseModel):
    sheet_name: str
    header_row_number: int
    total_rows: int
    summary: dict
    items: list[dict]


@router.post(
    "/excel/preview",
    response_model=SheetPreviewOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def preview_excel_sheet_endpoint(
    file: UploadFile = File(...),
    sheet_index: int = Form(0),
    mode: ImportBatchMode = Form(ImportBatchMode.create_plan),
    production_plan_id: int | None = Form(None),
    row_selection: str | None = Form(None),
    template_id: int | None = Query(None),
    normalize_hanger_quantity: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> SheetPreviewOut:
    from app.services.plan_import_service import preview_excel_sheet

    resolved_mapping = None
    rule_profile_id = None
    if template_id is not None:
        template = await db.get(ImportTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Шаблон не найден")
        if not template.is_active:
            raise HTTPException(status_code=400, detail="Шаблон неактивен")
        resolved_mapping = dict(template.column_mapping)
        rule_profile_id = (
            await db.execute(
                select(RouteRuleProfile.id)
                .where(RouteRuleProfile.import_template_id == template_id)
                .order_by(desc(RouteRuleProfile.is_active), desc(RouteRuleProfile.priority), RouteRuleProfile.id.asc())
                .limit(1)
            )
        ).scalars().first()

    content = await file.read()
    result = await preview_excel_sheet(
        db,
        filename=file.filename or "workbook.xls",
        content=content,
        sheet_index=sheet_index,
        mode=mode,
        production_plan_id=production_plan_id,
        column_mapping=resolved_mapping,
        row_selection=row_selection,
        rule_profile_id=rule_profile_id,
        normalize_hanger_quantity=normalize_hanger_quantity,
    )
    return SheetPreviewOut(**result)


_SIMULATED_PLAN_HEADERS = [
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
]


class SimulatedPlanRow(BaseModel):
    """Строка «Упаковочного плана» для бесфайлового импорта.

    Поля повторяют колонки шаблона в их порядке; `None` — пустая ячейка
    (строка-продолжение группы раскроя несёт только `output_length_m`
    и `output_qty`).
    """

    sku: str
    replenishment: str | None = "ТЗ"
    name: str | None = None
    raw_stock: float | None = None
    color: str | None = None
    qty_per_27: float | None = None
    length_m: float | None = None
    operation: str | None = None
    packaging: str | None = None
    note: str | None = None
    output_length_m: float | None = None
    output_qty: float | None = None
    west: float | None = None
    east: float | None = None
    kind: str | None = None

    def as_cells(self) -> list[object]:
        return [
            self.sku,
            self.replenishment,
            self.name,
            self.raw_stock,
            self.color,
            self.qty_per_27,
            self.length_m,
            self.operation,
            self.packaging,
            self.note,
            self.output_length_m,
            self.output_qty,
            self.west,
            self.east,
            self.kind,
        ]


class SimulatedPlanImportIn(BaseModel):
    rows: list[SimulatedPlanRow] = Field(min_length=1)
    sheet_name: str = "totalplan"
    mode: ImportBatchMode = ImportBatchMode.create_plan
    production_plan_id: int | None = None
    template_id: int | None = None
    row_selection: str | None = None
    normalize_hanger_quantity: bool = True


def _simulated_plan_workbook(rows: list[SimulatedPlanRow], sheet_name: str) -> bytes:
    """Собрать «Упаковочный план» в памяти из строк (файл на диске не нужен)."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_name
    for _ in range(3):
        ws.append([])
    ws.append(list(_SIMULATED_PLAN_HEADERS))
    for row in rows:
        ws.append(row.as_cells())
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@router.post("/excel/simulate", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def import_simulated_excel(
    payload: SimulatedPlanImportIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(list(PLAN_OWNER_ROLES))),
) -> ImportPreviewOut:
    """Импорт плана без файла: строки приходят в теле запроса, xlsx
    собирается в памяти и проходит тот же change-set, что и upload.

    Заменяет хранимые e2e-фикстуры: сетапу теста не нужен xlsx в репозитории.
    """
    resolved_mapping = None
    rule_profile_id = None
    if payload.template_id is not None:
        resolved_mapping, rule_profile_id = await _resolve_template_context(
            db, payload.template_id, None
        )

    await _reject_legacy_plan_mutation(db, payload.production_plan_id)
    content = _simulated_plan_workbook(payload.rows, payload.sheet_name)
    try:
        result = await create_excel_import_change_set(
            db,
            filename=f"simulated-{payload.sheet_name}.xlsx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sheet_index=0,
            mode=payload.mode,
            production_plan_id=payload.production_plan_id,
            column_mapping=resolved_mapping,
            row_selection=payload.row_selection,
            template_id=payload.template_id,
            rule_profile_id=rule_profile_id,
            normalize_hanger_quantity=payload.normalize_hanger_quantity,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ImportPreviewOut(**result)


class ImportLightItemOut(BaseModel):
    """Лёгкая строка импорта (спека §4.3): без after_data."""

    item_id: int
    source_row_numbers: list[int]
    source_sku: str | None
    source_name: str | None
    quantity: str | int | float | None
    status: str
    change_action: str
    codes: list[str]
    # Раздельно от `codes`: агрегаты диалога применения считают «С ошибками»
    # только по errors, а `codes` склеивает ошибки с предупреждениями (#172).
    errors: list[str]
    warnings: list[str]


class ImportFullItemOut(BaseModel):
    """Полная строка импорта для раскрытия в диффе (`?full=1`)."""

    id: int
    source_row_number: int | None
    source_ref: str | None
    source_sku: str | None
    change_action: str
    status: str
    warnings: list[str]
    errors: list[str]
    after_data: dict | None
    plan_position_id: int | None


class ImportBatchItemsOut(BaseModel):
    batch_id: int
    change_set_id: int
    items: list[ImportLightItemOut]
    next_cursor: int | None
    total: int


@router.get(
    "/batches/{batch_id}/items",
    response_model=ImportBatchItemsOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def list_import_batch_items(
    batch_id: int,
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> ImportBatchItemsOut:
    """Постраничные лёгкие строки батча (спека §4.3). UI пагинации нет:
    таблица читает все страницы курсором и показывает строки сразу.
    `total` — размер change set целиком, курсор на него не влияет."""
    from app.models.production_plan import PlanChangeItem
    from app.services.plan_import_service import serialize_light_item

    change_set_id = await db.scalar(
        select(PlanChangeSet.id)
        .where(PlanChangeSet.import_batch_id == batch_id)
        .order_by(desc(PlanChangeSet.id))
        .limit(1)
    )
    if change_set_id is None:
        raise HTTPException(status_code=404, detail="Набор изменений для партии не найден")
    rows = (
        await db.execute(
            select(PlanChangeItem)
            .where(PlanChangeItem.change_set_id == change_set_id, PlanChangeItem.id > cursor)
            .order_by(PlanChangeItem.id)
            .limit(limit + 1)
        )
    ).scalars().all()
    page, has_more = rows[:limit], len(rows) > limit
    total = await db.scalar(
        select(func.count())
        .select_from(PlanChangeItem)
        .where(PlanChangeItem.change_set_id == change_set_id)
    )
    return {
        "batch_id": batch_id,
        "change_set_id": change_set_id,
        "items": [serialize_light_item(item) for item in page],
        "next_cursor": page[-1].id if has_more and page else None,
        "total": total or 0,
    }


@router.get("/items/{item_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def get_import_item(
    item_id: int,
    full: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> ImportLightItemOut | ImportFullItemOut:
    """Одна строка импорта: лёгкая по умолчанию, `?full=1` — с after_data
    (раскрытие в диффе). Возврат — union двух моделей, поэтому response_model
    выключен: FastAPI не строит поле ответа из union-аннотации."""
    from app.models.production_plan import PlanChangeItem
    from app.services.plan_import_service import serialize_item, serialize_light_item

    item = await db.get(PlanChangeItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Элемент импорта не найден")
    return serialize_item(item) if full else serialize_light_item(item)


class ImportRecentOut(BaseModel):
    id: int
    production_plan_id: int
    change_set_id: int | None
    template_id: int | None = None
    rule_profile_id: int | None = None
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
    route_selection_diagnostics: dict
    created_at: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/recent", response_model=list[ImportRecentOut], dependencies=[Depends(require_role(list(READER_ROLES)))])
async def list_recent_imports(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[ImportRecentOut]:
    result = await db.execute(
        select(ImportBatch, ProductionPlan, ImportFile, PlanChangeSet)
        .join(ProductionPlan, ImportBatch.production_plan_id == ProductionPlan.id)
        .join(ImportFile, ImportBatch.source_file_id == ImportFile.id)
        .outerjoin(PlanChangeSet, PlanChangeSet.import_batch_id == ImportBatch.id)
        .where(ProductionPlan.deleted_at.is_(None))
        # `id` — тай-брейкер: без него порядок батчей с одинаковым `created_at`
        # не определён, и список «переезжает» между перерисовками. LIFO-владелец
        # отката считается по `applied_at` и на равных метках берёт первый в
        # списке (`frontend/src/features/planning/lib/appliedBatches.ts`), то есть
        # зависел от этого порядка.
        .order_by(desc(ImportBatch.created_at), desc(ImportBatch.id))
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
                template_id=batch.template_id,
                rule_profile_id=batch.rule_profile_id,
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
                route_selection_diagnostics=batch.route_selection_diagnostics or {},
                created_at=batch.created_at.isoformat() if batch.created_at else "",
            )
        )
    return items


class ImportPositionOut(BaseModel):
    id: int
    source_row_number: int | None
    source_sku: str
    source_name: str | None
    quantity: str
    product_id: int | None
    product_name: str | None
    route_id: int | None
    route_name: str | None
    route_source: str | None
    route_origin: str | None
    route_match_quality: str | None
    route_match_reason: str | None
    route_assigned_at: str | None
    route_manual_confirmed_at: str | None
    status: str
    validation_status: str
    validation_errors: list
    import_batch_id: int | None


@router.get(
    "/{batch_id}/positions",
    response_model=list[ImportPositionOut],
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def list_import_positions(batch_id: int, db: AsyncSession = Depends(get_db)) -> list[ImportPositionOut]:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Партия импорта не найдена")

    positions = (
        await db.execute(
            select(PlanPosition)
            .where(PlanPosition.import_batch_id == batch_id)
            .order_by(PlanPosition.source_row_number)
        )
    ).scalars().all()
    # Батч-резолв маршрутов (#292/#296): раньше resolve_position_route звался
    # на каждую позицию. Ключ локального кэша включает source_payload, поэтому
    # у реальных строк батча он уникален и мемоизация не помогала — на батче
    # в 900 строк это десятки тысяч запросов.
    route_info_by_id = await resolve_position_routes_batch(db, positions)

    # Имена продуктов — одним запросом по колонке. Ответу нужно только
    # product.name, поэтому ORM-объекты Product не грузятся: у них есть
    # column_property с EXISTS по product_pairs и связи processing_flags/
    # composition, и на каждый продукт это отдельная волна запросов.
    product_names: dict[int, str | None] = {}
    product_ids = {pos.product_id for pos in positions if pos.product_id is not None}
    if product_ids:
        for pid, pname in (
            await db.execute(
                select(Product.id, Product.name).where(Product.id.in_(product_ids))
            )
        ).all():
            product_names[pid] = pname

    result = []
    for pos in positions:
        route_info = route_info_by_id[pos.id]
        product_name = product_names.get(pos.product_id)
        result.append(
            ImportPositionOut(
                id=pos.id,
                source_row_number=pos.source_row_number,
                source_sku=pos.source_sku,
                source_name=pos.source_name,
                quantity=str(pos.quantity),
                product_id=pos.product_id,
                product_name=product_name,
                route_id=route_info.route_id,
                route_name=route_info.route_name,
                route_source=route_info.source,
                route_origin=route_info.route_origin,
                route_match_quality=route_info.route_match_quality,
                route_match_reason=route_info.route_match_reason,
                route_assigned_at=route_info.route_assigned_at.isoformat() if route_info.route_assigned_at else None,
                route_manual_confirmed_at=(
                    route_info.route_manual_confirmed_at.isoformat() if route_info.route_manual_confirmed_at else None
                ),
                status=pos.status.value,
                validation_status=pos.validation_status.value,
                validation_errors=pos.validation_errors or [],
                import_batch_id=pos.import_batch_id,
            )
        )

    return result


@router.get("/files/{file_id}/download", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def download_import_file(file_id: int, db: AsyncSession = Depends(get_db)):
    from urllib.parse import quote

    from fastapi.responses import FileResponse

    file = await db.get(ImportFile, file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if not file.stored_path:
        raise HTTPException(status_code=404, detail="Содержимое файла недоступно")

    path = Path(file.stored_path)
    # exists() блокирует event loop воркера, поэтому уходит в поток (#267).
    if not await asyncio.to_thread(path.exists):
        raise HTTPException(status_code=404, detail="Файл не найден на диске")

    encoded_name = quote(file.original_filename)
    return FileResponse(
        path=path,
        filename=file.original_filename,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )
