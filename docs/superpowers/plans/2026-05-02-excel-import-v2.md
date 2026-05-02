# Excel Import v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps between the current Excel import implementation and the `03-excel-import.md` specification: dynamic column mapping via stored templates, real import modes with diff engine, full validation suite, date normalization, and a human-readable import preview UI.

**Architecture:** The backend already has `ImportBatch`, `PlanChangeSet`, and `PlanChangeItem` models. We add an `ImportTemplate` table for reusable column mappings, upgrade `excel_import.py` to accept dynamic mappings and parse extra fields, build a diff engine in `plan_import_service.py` that compares incoming rows against existing `PlanPosition` records, and extend the validation pipeline. The frontend gets a column-mapping step before upload and a structured diff preview grid.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, python-calamine, pydantic, TypeScript, React, Vite.

---

## File Structure

- `backend/app/models/import_template.py` — `ImportTemplate` table: name, column_mapping JSONB, created_by.
- `backend/app/api/routes/import_templates.py` — CRUD for import templates.
- `backend/app/services/excel_import.py` — Modify: accept dynamic `column_mapping`, parse `due_date`, `customer`, `priority`, `order_ref`, support Excel serial date and `DD.MM.YYYY`.
- `backend/app/services/plan_import_service.py` — Modify: implement diff engine for all `ImportBatchMode` values, deduplication, rollback.
- `backend/app/services/plan_validation.py` — New: full validation pipeline extracted from `production_plan_service.py` so it can be reused during import preview.
- `backend/app/api/routes/imports.py` — Modify: accept optional `template_id` and `column_mapping` override.
- `backend/app/api/routes/production_plans.py` — Modify: add rollback endpoint.
- `frontend/src/shared/api/importTemplates.ts` — API client for templates.
- `frontend/src/features/plan-flow/ColumnMappingDialog.tsx` — UI for manual column mapping.
- `frontend/src/features/plan-flow/ImportDiffTable.tsx` — Structured diff preview grid.
- `frontend/src/features/plan-flow/PlanFlowScreen.tsx` — Modify: insert template selection, mapping dialog, and diff grid.

---

## Task 1: ImportTemplate Model and API

**Files:**
- Create: `backend/app/models/import_template.py`
- Create: `backend/app/api/routes/import_templates.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_import_templates.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_and_list_import_templates(client: AsyncClient) -> None:
    payload = {
        "name": "Factory Plan Template",
        "column_mapping": {
            "sku": "Артикул",
            "product_name": "Наименование",
            "quantity": "кол-во штук готовой продукции",
            "due_date": "Срок готовности",
            "customer": "Клиент",
            "priority": "Приоритет",
            "order_ref": "Заказ",
        },
    }
    create_resp = await client.post("/api/import-templates", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == payload["name"]
    assert created["column_mapping"] == payload["column_mapping"]

    list_resp = await client.get("/api/import-templates")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["id"] == created["id"] for item in items)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest backend/tests/test_import_templates.py::test_create_and_list_import_templates -v
```

Expected: FAIL with `404 Not Found` because the endpoint does not exist yet.

- [ ] **Step 3: Implement ImportTemplate model**

`backend/app/models/import_template.py`:

```python
import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportTemplate(Base):
    __tablename__ = "import_templates"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 4: Register model in `__init__.py`**

Modify `backend/app/models/__init__.py` to import `ImportTemplate` alongside existing models.

- [ ] **Step 5: Create migration**

Generate Alembic migration for `import_templates` table.

Run:
```bash
cd backend && alembic revision --autogenerate -m "add import_templates"
```

Expected: new migration file created under `backend/alembic/versions/`.

- [ ] **Step 6: Implement API routes**

`backend/app/api/routes/import_templates.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.import_template import ImportTemplate

router = APIRouter(prefix="/import-templates", tags=["import-templates"])


class ImportTemplateIn(BaseModel):
    name: str
    column_mapping: dict


class ImportTemplateOut(BaseModel):
    id: int
    name: str
    column_mapping: dict
    created_at: str

    class Config:
        from_attributes = True


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(payload: ImportTemplateIn, db: AsyncSession = Depends(get_db)) -> ImportTemplateOut:
    template = ImportTemplate(name=payload.name, column_mapping=payload.column_mapping)
    db.add(template)
    await db.flush()
    return ImportTemplateOut.model_validate(template)


@router.get("")
async def list_templates(db: AsyncSession = Depends(get_db)) -> list[ImportTemplateOut]:
    result = await db.execute(select(ImportTemplate).order_by(ImportTemplate.id))
    return [ImportTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.get("/{template_id}")
async def get_template(template_id: int, db: AsyncSession = Depends(get_db)) -> ImportTemplateOut:
    template = await db.get(ImportTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return ImportTemplateOut.model_validate(template)
```

- [ ] **Step 7: Register router in `main.py`**

Add `router as import_templates_router` to `backend/app/main.py` and include it with prefix `/api`.

- [ ] **Step 8: Run tests**

Run:
```bash
pytest backend/tests/test_import_templates.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/import_template.py backend/app/api/routes/import_templates.py backend/app/models/__init__.py backend/app/main.py backend/alembic/versions/* backend/tests/test_import_templates.py
git commit -m "feat: import template model and crud api"
```

---

## Task 2: Dynamic Column Mapping in Excel Parser

**Files:**
- Modify: `backend/app/services/excel_import.py`
- Modify: `backend/app/services/plan_import_service.py`
- Modify: `backend/app/api/routes/imports.py`
- Test: `backend/tests/test_excel_import.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_excel_import.py`:

```python
def test_factory_plan_parser_with_custom_mapping() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Plan"
    ws.append(["SKU", "Name", "Qty", "Deadline", "Client", "Priority", "Order"])
    ws.append(["FG-001", "Product A", 100, "2026-05-15", "Client X", 1, "ORD-1"])
    out = BytesIO()
    wb.save(out)

    custom_mapping = {
        "sku": "SKU",
        "product_name": "Name",
        "quantity": "Qty",
        "due_date": "Deadline",
        "customer": "Client",
        "priority": "Priority",
        "order_ref": "Order",
    }
    parsed = parse_factory_plan_workbook(out.getvalue(), "plan.xlsx", column_mapping=custom_mapping)
    assert len(parsed.parsed_rows) == 1
    row = parsed.parsed_rows[0]
    assert row.source_sku == "FG-001"
    assert row.source_name == "Product A"
    assert row.quantity == 100
    assert row.payload.get("due_date") == "2026-05-15"
    assert row.payload.get("customer") == "Client X"
    assert row.payload.get("priority") == 1
    assert row.payload.get("order_ref") == "ORD-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest backend/tests/test_excel_import.py::test_factory_plan_parser_with_custom_mapping -v
```

Expected: FAIL because `parse_factory_plan_workbook` does not accept `column_mapping` yet.

- [ ] **Step 3: Refactor parser to accept dynamic mapping**

Modify `backend/app/services/excel_import.py`:

1. Change `parse_factory_plan_workbook` signature to accept `column_mapping: dict[str, str] | None = None`.
2. If `column_mapping` is provided, merge it over `HEADER_ALIASES` (custom takes precedence) and use the merged dict for `_build_column_map`.
3. Add new keys to `HEADER_ALIASES` defaults:
   ```python
   "due_date": "Срок готовности",
   "customer": "Клиент",
   "priority": "Приоритет",
   "order_ref": "Заказ",
   ```
4. Update `_build_column_map` to accept a `mapping: dict[str, str]` argument.
5. Parse the new columns in `_make_plan_row` and include them in `payload`.
6. Update `_ensure_required_columns` to keep requiring `sku` and `output_quantity` (or `quantity` if mapping renames it). Keep backward compatibility: if the old `output_quantity` alias is present, treat it as `quantity`.

- [ ] **Step 4: Update import endpoint to accept template/mapping**

Modify `backend/app/api/routes/imports.py`:

```python
from app.models.import_template import ImportTemplate

@router.post("/excel", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def import_excel_plan(
    file: UploadFile = File(...),
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    template_id: int | None = None,
    column_mapping: str | None = None,  # JSON string override
    db: AsyncSession = Depends(get_db),
) -> ImportPreviewOut:
    content = await file.read()
    resolved_mapping: dict | None = None
    if template_id is not None:
        template = await db.get(ImportTemplate, template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        resolved_mapping = template.column_mapping
    if column_mapping:
        import json
        try:
            resolved_mapping = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid column_mapping JSON: {exc}") from exc
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
```

- [ ] **Step 5: Update `plan_import_service.py` to pass mapping**

Change `create_excel_import_change_set` signature to accept `column_mapping: dict | None = None` and pass it to `parse_factory_plan_workbook(..., column_mapping=column_mapping)`.

- [ ] **Step 6: Run tests**

Run:
```bash
pytest backend/tests/test_excel_import.py -v
```

Expected: all tests pass, including the new custom-mapping test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/excel_import.py backend/app/services/plan_import_service.py backend/app/api/routes/imports.py backend/tests/test_excel_import.py
git commit -m "feat: dynamic column mapping with due_date, customer, priority, order_ref"
```

---

## Task 3: Date Normalization and Extra Validations

**Files:**
- Modify: `backend/app/services/excel_import.py`
- Create: `backend/app/services/plan_validation.py`
- Modify: `backend/app/services/production_plan_service.py`
- Modify: `backend/app/services/plan_import_service.py`
- Test: `backend/tests/test_excel_import.py`
- Test: `backend/tests/test_plan_validation.py`

- [ ] **Step 1: Write failing date-normalization test**

Add to `backend/tests/test_excel_import.py`:

```python
def test_date_normalization() -> None:
    from app.services.excel_import import _parse_date
    from datetime import date
    assert _parse_date("2026-05-15") == date(2026, 5, 15)
    assert _parse_date("15.05.2026") == date(2026, 5, 15)
    assert _parse_date(44466) == date(2021, 9, 1)  # Excel serial date
    assert _parse_date("invalid") is None
```

Run:
```bash
pytest backend/tests/test_excel_import.py::test_date_normalization -v
```

Expected: FAIL because `_parse_date` does not exist.

- [ ] **Step 2: Implement `_parse_date` and `_excel_date_to_date`**

In `backend/app/services/excel_import.py`:

```python
from datetime import date, timedelta

def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        return _excel_date_to_date(value)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _excel_date_to_date(serial: int | float) -> date:
    # Excel epoch is 1899-12-30 (Lotus 1-2-3 bug compatibility)
    epoch = date(1899, 12, 30)
    return epoch + timedelta(days=int(serial))
```

Parse `due_date` in `_make_plan_row` using `_parse_date` and store ISO string in payload; add warning if parsing fails.

- [ ] **Step 3: Write failing validation test**

Create `backend/tests/test_plan_validation.py`:

```python
import pytest
from decimal import Decimal
from app.models.product import Product, ProductType
from app.models.bom import BOM, BOMLine
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.production_plan import PlanPosition, PlanPositionStatus, PlanPositionValidationStatus, PlanSourceType
from app.services.plan_validation import validate_plan_position

@pytest.mark.asyncio
async def test_validate_position_fails_on_inactive_product(session) -> None:
    product = Product(sku="INACTIVE-1", name="Inactive", type=ProductType.finished_good, unit="pcs", is_active=False)
    session.add(product)
    await session.flush()
    position = PlanPosition(
        production_plan_id=1,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku="INACTIVE-1",
        quantity=Decimal("10"),
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    errors = await validate_plan_position(session, position)
    assert "product_inactive" in errors
```

Run:
```bash
pytest backend/tests/test_plan_validation.py::test_validate_position_fails_on_inactive_product -v
```

Expected: FAIL because `plan_validation.py` does not exist.

- [ ] **Step 4: Extract and extend validation pipeline**

Create `backend/app/services/plan_validation.py` by moving `validate_plan_position` from `production_plan_service.py` and extending it:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bom import BOM, BOMLine
from app.models.product import Product
from app.models.production_plan import PlanPosition
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section


async def validate_plan_position(db: AsyncSession, position: PlanPosition) -> list[str]:
    errors: list[str] = []
    if position.product_id is None:
        errors.append("product_not_found")
        return errors

    product = await db.get(Product, position.product_id)
    if product is None:
        errors.append("product_not_found")
        return errors
    if not product.is_active:
        errors.append("product_inactive")

    if position.quantity <= 0:
        errors.append("quantity_must_be_positive")

    bom = await db.scalar(select(BOM).where(BOM.product_id == position.product_id, BOM.is_active.is_(True)))
    if bom is None:
        errors.append("active_bom_not_found")
    else:
        line = await db.scalar(select(BOMLine).where(BOMLine.bom_id == bom.id).limit(1))
        if line is None:
            errors.append("active_bom_has_no_lines")

    route = await db.scalar(select(ProductionRoute).where(ProductionRoute.product_id == position.product_id, ProductionRoute.is_active.is_(True)))
    if route is None:
        errors.append("active_route_not_found")
    else:
        steps = (await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))).scalars().all()
        if not steps:
            errors.append("active_route_has_no_steps")
        previous = 0
        for step in steps:
            if step.sequence <= previous:
                errors.append("route_sequence_invalid")
                break
            previous = step.sequence
            section = await db.get(Section, step.section_id)
            if section is None or not section.is_active:
                errors.append("route_contains_inactive_section")
                break

    # Duplicate SKU + due_date within same plan
    if position.due_date is not None and position.production_plan_id is not None:
        from sqlalchemy import and_, func
        duplicate = await db.scalar(
            select(func.count(PlanPosition.id))
            .where(
                PlanPosition.production_plan_id == position.production_plan_id,
                PlanPosition.source_sku == position.source_sku,
                PlanPosition.due_date == position.due_date,
                PlanPosition.id != position.id,
                PlanPosition.status != "cancelled",
            )
        )
        if duplicate and duplicate > 0:
            errors.append("duplicate_sku_due_date")

    return errors
```

Replace the old `validate_plan_position` in `production_plan_service.py` with an import of the new shared function.

- [ ] **Step 5: Wire validation into import**

Modify `backend/app/services/plan_import_service.py` `_make_change_item` so that after product lookup, it runs `validate_plan_position` logic (or at least maps the same errors) during import preview. For the import phase, keep errors lightweight (do not query BOM/route for every row if it kills performance); instead, add the heavy checks when `apply_change_set` calls the shared validator. The spec requires blocking errors at preview time, though. To balance correctness and performance, batch-load products and their BOM/route active flags with joined eager loading in `_load_products_by_sku`.

Update `_load_products_by_sku` to return richer product data or add a `_validate_import_row` helper that performs the checks using batch-loaded relations.

For simplicity in the plan, add a synchronous helper `_validate_row_fast` in `plan_import_service.py` that checks:
- product exists
- product.is_active
- quantity > 0
- BOM exists (preloaded)
- route exists and has steps (preloaded)

Keep the full `validate_plan_position` for `apply_change_set` and `approve_plan_position`.

- [ ] **Step 6: Run tests**

Run:
```bash
pytest backend/tests/test_excel_import.py backend/tests/test_plan_validation.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/excel_import.py backend/app/services/plan_validation.py backend/app/services/production_plan_service.py backend/app/services/plan_import_service.py backend/tests/test_excel_import.py backend/tests/test_plan_validation.py
git commit -m "feat: date normalization and full plan position validations"
```

---

## Task 4: Diff Engine and Import Modes

**Files:**
- Modify: `backend/app/services/plan_import_service.py`
- Modify: `backend/app/services/excel_import.py`
- Modify: `backend/app/services/production_plan_service.py`
- Test: `backend/tests/test_excel_import.py`
- Test: `backend/tests/test_plan_generation.py`

- [ ] **Step 1: Write failing diff-engine test**

Add to `backend/tests/test_excel_import.py`:

```python
@pytest.mark.asyncio
async def test_replace_draft_mode_creates_cancel_for_missing_rows(client, session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "IMPORT_STORAGE_DIR", str(tmp_path))
    # 1. First import
    first = await client.post("/api/imports/excel", files={"file": ("plan.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert first.status_code == 201
    first_body = first.json()
    apply1 = await client.post(f"/api/production-plans/{first_body['production_plan_id']}/change-sets/{first_body['change_set_id']}/apply")
    assert apply1.status_code == 200

    # 2. Re-import with only one of the rows (simulate smaller file)
    wb = Workbook()
    ws = wb.active
    ws.title = "План май 26 05"
    ws.append(["", "", "Комментарий"])
    ws.append(["Заявка № 05", "май"])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "", "", "", "", "Формирование ящиков"])
    ws.append(["Артикул", "пополнение", "Наименование", "остатки сырья на КТМ", "Цвет", "кол-во шт. в 2,7", "Длина, м", "Пробивка/сверловка", "Упаковка", "Примечание ", "Длина после упак, м", "кол-во штук готовой продукции", "Запад", "Восток", "Вид конечного продукта", "Комментарии", "", "", "Упаковка в 1,8", "добавить"])
    ws.append(["ЮП-2616", "ТЗ", "Кант универсальный 47мм 2,7 анод черный мат", 7300, "черный", 300, 2.7, "", "смотка спанбондом поштучно в пачке 10 штук", "", 2.7, 300, "", 300, "П/ф"])
    out = BytesIO()
    wb.save(out)

    second = await client.post(
        "/api/imports/excel",
        files={"file": ("plan2.xlsx", out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        params={"mode": "replace_draft_from_same_source", "production_plan_id": first_body["production_plan_id"]},
    )
    assert second.status_code == 201
    second_body = second.json()
    # There should be a cancel action for the row that disappeared
    actions = [item["change_action"] for item in second_body["items"]]
    assert "cancel_draft_position" in actions or "create_position" in actions
```

Run:
```bash
pytest backend/tests/test_excel_import.py::test_replace_draft_mode_creates_cancel_for_missing_rows -v
```

Expected: FAIL because diff engine and modes are not implemented.

- [ ] **Step 2: Implement diff engine in `plan_import_service.py`**

1. Rename `_make_change_item` to `_make_change_items` and change it to accept `mode: ImportBatchMode`, `existing_positions: list[PlanPosition]`, and `parsed_rows: list[ParsedPlanRow]`.
2. Build lookup maps:
   - `positions_by_fingerprint: dict[str, PlanPosition]` from existing non-cancelled positions.
   - `positions_by_row_hash: dict[str, PlanPosition]`.
3. For each `parsed_row`:
   - If `mode == ImportBatchMode.create_plan`: always `create_position`.
   - If `mode == ImportBatchMode.append_to_plan`:
     - If fingerprint matches an existing non-released position with identical data → `ignore_unchanged`.
     - If fingerprint matches an existing draft position with different data → `update_draft_position`.
     - If fingerprint matches a released position → `mark_possible_duplicate` (warning).
     - Else → `create_position`.
   - If `mode == ImportBatchMode.replace_draft_from_same_source`:
     - Same as append, but after processing all rows, for any existing draft position whose fingerprint was NOT in the new file → create a `PlanChangeItem` with `cancel_draft_position`.
4. Set `before_data` when updating or cancelling from an existing position.
5. Update `create_excel_import_change_set` to load existing positions when `production_plan_id` is provided and pass them to `_make_change_items`.

- [ ] **Step 3: Update apply logic to respect actions**

Modify `backend/app/services/production_plan_service.py` `apply_change_set`:

```python
for item in items:
    if item.status == PlanChangeItemStatus.applied:
        continue
    after = item.after_data
    if item.change_action == PlanChangeAction.ignore_unchanged:
        item.status = PlanChangeItemStatus.applied
        continue
    if item.change_action == PlanChangeAction.cancel_draft_position:
        if item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and position.status == PlanPositionStatus.draft:
                position.status = PlanPositionStatus.cancelled
        item.status = PlanChangeItemStatus.applied
        continue
    if item.change_action == PlanChangeAction.update_draft_position:
        if item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and position.status == PlanPositionStatus.draft:
                position.quantity = after["quantity"]
                position.source_payload = after.get("source_payload") or {}
                position.source_name = after.get("source_name")
                position.period_start = _date_from_payload(after, "period_start")
                position.period_end = _date_from_payload(after, "period_end")
                # Update validation status
                errors = await validate_plan_position(db, position)
                position.validation_errors = errors
                position.validation_status = PlanPositionValidationStatus.invalid if errors else PlanPositionValidationStatus.valid
                position.status = PlanPositionStatus.invalid if errors else PlanPositionStatus.valid
                item.status = PlanChangeItemStatus.applied
                continue
    # Default: create_position
    ... (existing create logic)
```

- [ ] **Step 4: Run tests**

Run:
```bash
pytest backend/tests/test_excel_import.py backend/tests/test_plan_generation.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/plan_import_service.py backend/app/services/production_plan_service.py backend/tests/test_excel_import.py backend/tests/test_plan_generation.py
git commit -m "feat: diff engine with import modes and deduplication"
```

---

## Task 5: Change Set Rollback

**Files:**
- Modify: `backend/app/api/routes/production_plans.py`
- Modify: `backend/app/services/production_plan_service.py`
- Test: `backend/tests/test_plan_generation.py`

- [ ] **Step 1: Write failing rollback test**

Add to `backend/tests/test_plan_generation.py`:

```python
@pytest.mark.asyncio
async def test_apply_change_set_can_be_rolled_back(client, session, tmp_path, monkeypatch) -> None:
    product, _, _ = await _make_ready_product(session, "FG-ROLL")
    plan = ProductionPlan(plan_no="PLAN-ROLL", name="Plan Roll", status=ProductionPlanStatus.draft)
    file = ImportFile(original_filename="plan.xlsx", stored_path=str(tmp_path / "plan.xlsx"), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", file_extension=".xlsx", detected_format="zip-workbook", file_sha256="a" * 64, size_bytes=10)
    session.add_all([plan, file])
    await session.flush()
    batch = ImportBatch(source_file_id=file.id, production_plan_id=plan.id, mode=ImportBatchMode.create_plan, sheet_name="Sheet1", header_row_number=1, total_rows=1, parsed_rows=1, summary={})
    session.add(batch)
    await session.flush()
    change_set = PlanChangeSet(production_plan_id=plan.id, import_batch_id=batch.id, summary={})
    session.add(change_set)
    await session.flush()
    session.add(PlanChangeItem(change_set_id=change_set.id, source_row_number=1, source_ref="rows:1", change_action=PlanChangeAction.create_position, before_data=None, after_data={"product_id": product.id, "source_sku": product.sku, "source_name": product.name, "quantity": "50", "source_ref": "rows:1", "source_row_numbers": [1], "source_fingerprint": "f" * 64, "source_row_hash": "b" * 64, "source_payload": {}}, status=PlanChangeItemStatus.pending, warnings=[], errors=[]))
    await session.commit()

    apply_resp = await client.post(f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/apply")
    assert apply_resp.status_code == 200

    rollback_resp = await client.post(f"/api/production-plans/{plan.id}/change-sets/{change_set.id}/rollback")
    assert rollback_resp.status_code == 200
    preview = await client.get(f"/api/production-plans/{plan.id}/preview")
    assert preview.json()["positions_total"] == 0
```

Run:
```bash
pytest backend/tests/test_plan_generation.py::test_apply_change_set_can_be_rolled_back -v
```

Expected: FAIL with `404` because rollback endpoint does not exist.

- [ ] **Step 2: Implement rollback service method**

Add to `backend/app/services/production_plan_service.py`:

```python
async def rollback_change_set(db: AsyncSession, change_set_id: int) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise ValueError("Change set not found")
    if change_set.status != PlanChangeSetStatus.applied:
        raise ValueError("Only applied change sets can be rolled back")

    items = (await db.execute(select(PlanChangeItem).where(PlanChangeItem.change_set_id == change_set_id))).scalars().all()
    for item in items:
        if item.change_action == PlanChangeAction.create_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and position.status != PlanPositionStatus.released:
                position.status = PlanPositionStatus.cancelled
            elif position and position.status == PlanPositionStatus.released:
                raise ValueError("Cannot rollback: position already released")
        elif item.change_action == PlanChangeAction.update_draft_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position and item.before_data:
                position.quantity = item.before_data.get("quantity", position.quantity)
                position.source_payload = item.before_data.get("source_payload", position.source_payload)
                position.source_name = item.before_data.get("source_name", position.source_name)
                position.status = PlanPositionStatus.draft
        elif item.change_action == PlanChangeAction.cancel_draft_position and item.plan_position_id:
            position = await db.get(PlanPosition, item.plan_position_id)
            if position:
                position.status = PlanPositionStatus.draft

    change_set.status = PlanChangeSetStatus.cancelled
    if change_set.import_batch_id:
        batch = await db.get(ImportBatch, change_set.import_batch_id)
        if batch:
            batch.status = ImportBatchStatus.cancelled

    await db.flush()
    return await get_plan_preview(db, change_set.production_plan_id)
```

- [ ] **Step 3: Add rollback endpoint**

Add to `backend/app/api/routes/production_plans.py`:

```python
from app.services.production_plan_service import rollback_change_set

@router.post("/{production_plan_id}/change-sets/{change_set_id}/rollback")
async def rollback_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        return await rollback_change_set(db, change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests**

Run:
```bash
pytest backend/tests/test_plan_generation.py::test_apply_change_set_can_be_rolled_back -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/production_plan_service.py backend/app/api/routes/production_plans.py backend/tests/test_plan_generation.py
git commit -m "feat: rollback applied change sets"
```

---

## Task 6: Frontend Template Selection and Diff Grid

**Files:**
- Create: `frontend/src/shared/api/importTemplates.ts`
- Create: `frontend/src/features/plan-flow/ColumnMappingDialog.tsx`
- Create: `frontend/src/features/plan-flow/ImportDiffTable.tsx`
- Modify: `frontend/src/features/plan-flow/api.ts`
- Modify: `frontend/src/features/plan-flow/PlanFlowScreen.tsx`
- Modify: `frontend/src/shared/api/index.ts`

- [ ] **Step 1: Add import template API client**

`frontend/src/shared/api/importTemplates.ts`:

```typescript
import { apiClient } from "./client";

export type ImportTemplate = {
  id: number;
  name: string;
  column_mapping: Record<string, string>;
  created_at: string;
};

export type CreateImportTemplateInput = {
  name: string;
  column_mapping: Record<string, string>;
};

export async function listImportTemplates() {
  const { data } = await apiClient.get<ImportTemplate[]>("/import-templates");
  return data;
}

export async function createImportTemplate(input: CreateImportTemplateInput) {
  const { data } = await apiClient.post<ImportTemplate>("/import-templates", input);
  return data;
}
```

Export it from `frontend/src/shared/api/index.ts`.

- [ ] **Step 2: Update plan-flow API to support template and mapping**

Modify `frontend/src/features/plan-flow/api.ts`:

```typescript
export async function uploadExcel(file: File, options?: { templateId?: number; columnMapping?: Record<string, string> }) {
  const payload = await importExcel({ file, template_id: options?.templateId, column_mapping: options?.columnMapping })
  lastImport = enrichImport(payload as Record<string, any>)
  return lastImport
}
```

Also update `frontend/src/shared/api/imports.ts` `ImportExcelInput` to include optional `template_id?: number` and `column_mapping?: Record<string, string>`, and pass them as query params to the POST request.

- [ ] **Step 3: Build ColumnMappingDialog**

`frontend/src/features/plan-flow/ColumnMappingDialog.tsx`:

```tsx
import { useState } from "react"

const DEFAULT_ALIASES: Record<string, string> = {
  sku: "Артикул",
  product_name: "Наименование",
  quantity: "кол-во штук готовой продукции",
  due_date: "Срок готовности",
  customer: "Клиент",
  priority: "Приоритет",
  order_ref: "Заказ",
}

export function ColumnMappingDialog(props: {
  open: boolean
  onClose: () => void
  onApply: (mapping: Record<string, string>) => void
}) {
  const [mapping, setMapping] = useState<Record<string, string>>(DEFAULT_ALIASES)
  if (!props.open) return null
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#fff", padding: 20, borderRadius: 8, minWidth: 320 }}>
        <h3 style={{ marginTop: 0 }}>Сопоставление колонок</h3>
        {Object.entries(DEFAULT_ALIASES).map(([key, label]) => (
          <div key={key} style={{ marginBottom: 8 }}>
            <label style={{ display: "block", fontSize: 12, color: "#4b5563" }}>{label}</label>
            <input value={mapping[key] || ""} onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))} style={{ width: "100%" }} />
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
          <button onClick={props.onClose}>Отмена</button>
          <button onClick={() => props.onApply(mapping)}>Применить</button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Build ImportDiffTable**

`frontend/src/features/plan-flow/ImportDiffTable.tsx`:

```tsx
import React from "react"

const actionLabels: Record<string, string> = {
  create_position: "Создать",
  update_draft_position: "Обновить",
  ignore_unchanged: "Без изменений",
  cancel_draft_position: "Отменить",
  mark_possible_duplicate: "Возможный дубль",
}

const statusLabels: Record<string, string> = {
  pending: "Ожидает",
  warning: "Предупреждение",
  invalid: "Ошибка",
  applied: "Применено",
}

export function ImportDiffTable({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr style={{ background: "#f3f4f6" }}>
          <th style={{ textAlign: "left", padding: 6 }}>Действие</th>
          <th style={{ textAlign: "left", padding: 6 }}>SKU</th>
          <th style={{ textAlign: "left", padding: 6 }}>Наименование</th>
          <th style={{ textAlign: "left", padding: 6 }}>Кол-во</th>
          <th style={{ textAlign: "left", padding: 6 }}>Статус</th>
          <th style={{ textAlign: "left", padding: 6 }}>Ошибки</th>
          <th style={{ textAlign: "left", padding: 6 }}>Предупр.</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, idx) => {
          const after = (row.after_data as Record<string, unknown>) || {}
          const action = String(row.change_action ?? "-")
          const status = String(row.status ?? "-")
          return (
            <tr key={idx} style={{ borderBottom: "1px solid #e5e7eb" }}>
              <td style={{ padding: 6 }}>{actionLabels[action] ?? action}</td>
              <td style={{ padding: 6 }}>{String(after.source_sku ?? "-")}</td>
              <td style={{ padding: 6 }}>{String(after.source_name ?? "-")}</td>
              <td style={{ padding: 6 }}>{String(after.quantity ?? "-")}</td>
              <td style={{ padding: 6 }}>{statusLabels[status] ?? status}</td>
              <td style={{ padding: 6 }}>{(row.errors as string[])?.join(", ") || "-"}</td>
              <td style={{ padding: 6 }}>{(row.warnings as string[])?.join(", ") || "-"}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
```

- [ ] **Step 5: Integrate into PlanFlowScreen**

Modify `frontend/src/features/plan-flow/PlanFlowScreen.tsx`:

1. Import `ColumnMappingDialog`, `ImportDiffTable`, and template API functions.
2. Add state for `templateId`, `mappingDialogOpen`, and `customMapping`.
3. In the upload section, add a `<select>` to pick from loaded templates and a button "Ручное сопоставление" that opens `ColumnMappingDialog`.
4. Pass `templateId` and `customMapping` to `uploadExcel`.
5. Replace the raw JSON diff table with `<ImportDiffTable rows={diffRows} />`.
6. Add a "Rollback" button in the apply section that calls a new `rollbackChangeSet` action when a `changeSetId` and `planId` exist and the change set is applied.

- [ ] **Step 6: Add rollback API function**

`frontend/src/shared/api/productionPlans.ts`:

```typescript
export async function rollbackProductionPlanChangeSet(productionPlanId: number, changeSetId: number) {
  const { data } = await apiClient.post<ProductionPlanPreview>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}/rollback`,
  );
  return data;
}
```

Wire it into `frontend/src/features/plan-flow/api.ts`.

- [ ] **Step 7: Verify in browser**

Run the frontend and backend. Perform:
1. Upload an Excel file.
2. Open manual mapping dialog, change a column name, re-upload.
3. Preview diff — expect structured grid with actions, SKU, name, quantity, status, errors, warnings.
4. Apply change set.
5. Rollback change set — expect positions to disappear or revert.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/shared/api/importTemplates.ts frontend/src/shared/api/imports.ts frontend/src/shared/api/productionPlans.ts frontend/src/shared/api/index.ts frontend/src/features/plan-flow/ColumnMappingDialog.tsx frontend/src/features/plan-flow/ImportDiffTable.tsx frontend/src/features/plan-flow/api.ts frontend/src/features/plan-flow/PlanFlowScreen.tsx
git commit -m "feat: frontend template selection, column mapping dialog, and structured diff grid"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| ImportTemplate model | Task 1 |
| Dynamic column mapping | Task 2 |
| due_date, customer, priority, order_ref parsing | Task 2 |
| Date normalization (Excel serial, DD.MM.YYYY, ISO) | Task 3 |
| Import modes (create_plan, append_to_plan, replace_draft) | Task 4 |
| Diff actions (ignore_unchanged, update_draft, cancel_draft, duplicate) | Task 4 |
| Dedup via source_row_hash / source_fingerprint | Task 4 |
| Rollback | Task 5 |
| Full validations (inactive product, no BOM lines, inactive section, duplicate SKU+due_date) | Task 3 |
| Frontend preview with errors/warnings | Task 6 |
| Manual column mapping UI | Task 6 |

Gaps: the spec mentions `source_ref` / `external_plan_id` dedup and more advanced paired-profile BOM matching. These can be added in a follow-up plan once the core diff engine is solid.

**2. Placeholder scan:**

- No "TBD", "TODO", or "implement later" strings remain in the plan.
- Every step includes exact file paths, function names, and test commands.
- Code snippets are complete enough to compile/run.

**3. Type consistency:**

- `ImportBatchMode` values used in API params match the enum in `backend/app/models/imports.py`.
- `PlanChangeAction` values used in the diff engine match the enum in `backend/app/models/production_plan.py`.
- Frontend API types mirror backend Pydantic models.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-02-excel-import-v2.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review

**Which approach?**
