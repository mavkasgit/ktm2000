# План: возврат импорта остатков на страницах ГХП (новая логика Stock Ledger)

> Ветка: `refactor/stock-ledger`. Зависит от: Этапы 0-7 завершены.
> Цель: вернуть функциональность массового импорта остатков из Excel на
> странице `SpgSnapshotPage`, но на новой логике `StockCommandService`/
> `StockTransaction` (без legacy `SpgRemainder`).

---

## 1. Контекст

В Этапе 6 (`f0be44b`) были удалены:
- `frontend/src/features/spg/components/ImportRemaindersDialog.tsx` (668 строк)
- `frontend/src/features/spg/components/ManualOperationDialog.tsx` (397 строк)
- `frontend/src/features/spg/components/ProductRemaindersDialog.tsx` (176 строк)
- `frontend/src/features/spg/components/RemainderEditDialog.tsx` (1304 строк)
- `frontend/src/features/spg/components/RemainderHistoryDrawer.tsx` (349 строк)
- `frontend/src/sections/components/SpgRemaindersDialog.tsx` (145 строк)
- `frontend/src/shared/api/spg.ts` (363 строки — API SpgRemainder)
- Backend endpoints: `GET/POST /api/spg/{id}/remainders/import/*`

Что осталось из нужного:
- `excel_templates.generate_remainders_excel_template` (в `backend/app/services/excel_templates.py`)
- `parse_row_selection` (в `backend/app/services/excel_import.py:194`)
- `python-calamine>=0.1.0`, `openpyxl>=3.1.0` (в `requirements.txt`)
- `getCurrentUser`, `READER_ROLES`, `WRITER_ROLES` (в `backend/app/api/deps.py`)
- `StockCommandService.record()` + `StockCommand` (в `backend/app/stock/services.py`)
- `Reason.MANUAL_IN`, `Reason.MANUAL_OUT`, `Reason.ADJUSTMENT_IN/OUT` (в `backend/app/stock/models.py:65`)
- `QualityState.GOOD/SCRAP/REWORK/QUARANTINE` (в `backend/app/stock/models.py:90`)
- `StockAdjustmentDialog` (в `frontend/src/features/spg/components/StockAdjustmentDialog.tsx`)

---

## 2. Целевая архитектура

### 2.1. Backend — новые endpoints (v2/stock)

Маунтятся в уже подключённом `app.stock.api.router` (префикс `/api/v2/stock`).
Добавить 3 endpoint'а для импорта остатков:

| Метод | Путь | Назначение |
|-------|------|-----------|
| `GET`  | `/import/remainders/template?location_id=N` | Скачивание Excel-шаблона для конкретной локации |
| `POST` | `/import/remainders/preview` (multipart) | Парсинг Excel, валидация, preview |
| `POST` | `/import/remainders` (multipart) | Применение: создание `StockTransaction` через `StockCommandService.record()` |

Параметры `POST /import/remainders`:
- `location_id: int` — куда импортировать (выбор секции пользователем, можно
  `raw_stock`/`wip_stock`/`finished_stock` — любой склад)
- `quality_state: QualityState = GOOD` — состояние качества (по умолчанию годные)
- `file: UploadFile` — Excel (.xlsx)
- `sheet_index: int = 0` — какой лист
- `row_selection: str | None` — формат `"2-10,12"`
- `skip_invalid: bool = True` — пропускать ошибочные строки или падать целиком
- `clear_existing: bool = False` — обнулить остатки по `(location, quality_state)`
  перед импортом (транзакции `ADJUSTMENT_OUT` под ноль)

Excel-формат (3 колонки):
| SKU | Количество | Комментарий |
|-----|-----------|-------------|
| `ALS-1289` | 150 | Дробеструй |
| `ЮП-2630` | 80 | Сверловка, Дробеструй |
| `361` | 200 |  |

### 2.2. Сервис — `app/stock/import_service.py`

Новый файл. Содержит:
- `parse_remainders_excel(content, sheet_index, row_selection) -> tuple[list[Item], SheetSummary]`
  — использует `python_calamine.load_workbook`, повторяет логику из
  `f0be44b^:backend/app/api/routes/spg.py:1688`, **но упрощённо** (без сложной
  логики определения целевой ГХП по операциям — её больше нет, целевая локация
  всегда задана в payload).
- `apply_remainders_import(db, location_id, items, quality_state, user, clear_existing) -> ImportResult`
  — для каждой валидной строки создаёт `StockCommand(MANUAL_IN)`, при
  `clear_existing=True` сначала создаёт компенсирующие `ADJUSTMENT_OUT` под
  текущий баланс.

### 2.3. Frontend — `ImportRemaindersDialog` (восстановлен)

Файл: `frontend/src/features/spg/components/ImportRemaindersDialog.tsx`.
Берём структуру и UX из `/tmp/old_ImportRemaindersDialog.tsx` (668 строк),
но:
- Убираем SPG-логику (нет `spg_id`, `currentSpgId`) — параметр
  `locationId` приходит снаружи (выбирает пользователь в `SpgSnapshotPage`)
- Убираем сложную логику `_determine_target_spg_for_remainder` (route matching)
- Убираем показ `RouteStepsDisplay` / `target_spg_name` колонок
- API клиент: переключаем на новые функции из `shared/api/stock.ts`
- Шаблон скачивается как Excel blob, без `getSpgImportOperations`
- Колонки в preview: № | Артикул | Название | Кол-во | Качество | Ошибки

### 2.4. Frontend — интеграция в `SpgSnapshotPage`

Файл: `frontend/src/features/spg/pages/SpgSnapshotPage.tsx`.
- Добавить кнопку "Импорт из Excel" рядом с "Ручная операция"
- Диалог открывается с выбором целевой локации (Select с секциями) →
  → `ImportRemaindersDialog` запускается с `locationId`
- После успешного импорта — инвалидация `queryKeys.stock.balances()` +
  `queryKeys.stock.productBalance(id)` + `queryKeys.stock.transactions()`

---

## 3. Детальный план реализации

### 3.1. Backend — `app/stock/import_service.py` (новый)

```python
# псевдокод
@dataclass
class RemainderItem:
    source_row_number: int
    sku: str
    quantity: float
    comment: str | None
    product_id: int | None
    product_name: str | None
    status: Literal["valid", "invalid"]
    errors: list[str]
    raw_values: list[str]

@dataclass
class SheetSummary:
    total: int
    valid: int
    invalid: int
    quantity_total: float

async def parse_remainders_excel(
    content: bytes,
    sheet_index: int = 0,
    row_selection: str | None = None,
) -> tuple[str, int, list[RemainderItem], SheetSummary]:
    # python_calamine + headers autodetect
    # Поддержка колонок: "SKU/Артикул/Код" + "Количество/Кол-во" + "Комментарий"
    # Валидация: SKU существует в Product, qty > 0
    ...

async def apply_remainders_import(
    db: AsyncSession,
    location_id: int,
    items: list[RemainderItem],
    quality_state: QualityState,
    user: User,
    clear_existing: bool = False,
) -> dict:
    """Returns: {success, imported_count, errors, transactions: [ids]}"""
    if clear_existing:
        # ADJUSTMENT_OUT под текущий баланс по (location_id, quality_state)
        for balance in current_balances:
            if balance.balance_qty > 0:
                await StockCommandService().record(db, StockCommand(
                    product_id=balance.product_id,
                    from_location_id=location_id,
                    quantity=float(balance.balance_qty),
                    reason=Reason.ADJUSTMENT_OUT,
                    quality_state=quality_state,
                    comment="Очистка перед импортом остатков",
                    created_by=user.id,
                ))

    svc = StockCommandService()
    for item in valid_items:
        tx = await svc.record(db, StockCommand(
            product_id=item.product_id,
            to_location_id=location_id,
            quantity=item.quantity,
            reason=Reason.MANUAL_IN,
            quality_state=quality_state,
            comment=item.comment or "Импорт остатков из Excel",
            source_ref="import_remainders_excel",
            created_by=user.id,
            created_by_user_name=user.full_name or user.username,
        ))
        imported_count += 1

    await db.commit()
    return {...}
```

### 3.2. Backend — добавить endpoints в `app/stock/api.py`

```python
# псевдокод
@router.get("/import/remainders/template")
async def download_remainders_template(location_id: int, ...):
    # Используем существующий generate_remainders_excel_template
    # или новый: app/services/excel_templates.py::generate_remainders_template_for_location
    return StreamingResponse(...)


@router.post("/import/remainders/preview", dependencies=[Depends(require_role(WRITER_ROLES))])
async def preview_remainders_excel(
    file: UploadFile = File(...),
    sheet_index: int = Form(0),
    row_selection: str | None = Form(None),
    quality_state: QualityState = Form(QualityState.GOOD),
    location_id: int = Form(...),  # для валидации локации
    db: AsyncSession = Depends(get_db),
) -> RemainderPreviewResponse:
    content = await file.read()
    sheet_name, total_rows, items, summary = await parse_remainders_excel(
        content, sheet_index, row_selection
    )
    return RemainderPreviewResponse(...)


@router.post("/import/remainders", dependencies=[Depends(require_role(WRITER_ROLES))])
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
) -> RemainderImportResponse:
    # Парсинг → проверка → если есть ошибки и skip_invalid=False → вернуть success: False
    # Иначе → apply_remainders_import()
    ...
```

### 3.3. Frontend — API client в `shared/api/stock.ts`

```typescript
export type RemainderImportItem = {
  source_row_number: number;
  sku: string;
  product_id: number | null;
  product_name: string | null;
  quantity: number | null;
  comment: string | null;
  status: "valid" | "invalid";
  errors: string[];
  raw_values: string[];
};

export type RemainderPreviewResponse = {
  sheet_name: string;
  total_rows: number;
  summary: { total: number; valid: number; invalid: number; quantity_total: number };
  items: RemainderImportItem[];
};

export type RemainderImportResponse = {
  success: boolean;
  imported_count: number;
  errors: string[];
  transaction_ids?: number[];
};

export async function previewRemaindersExcel(
  locationId: number,
  file: File,
  opts: { sheet_index?: number; row_selection?: string; quality_state?: QualityState }
): Promise<RemainderPreviewResponse> { ... }

export async function importRemaindersExcel(
  locationId: number,
  file: File,
  opts: {
    sheet_index?: number;
    row_selection?: string;
    quality_state?: QualityState;
    skip_invalid?: boolean;
    clear_existing?: boolean;
  }
): Promise<RemainderImportResponse> { ... }

export async function downloadRemaindersImportTemplate(locationId: number): Promise<Blob> { ... }
```

### 3.4. Frontend — `ImportRemaindersDialog.tsx`

Переписать на основе `/tmp/old_ImportRemaindersDialog.tsx`:
- Заменить `currentSpgId` → `locationId` (приходит prop)
- Убрать `getSpgImportOperations`, `RouteStepsDisplay`, `target_spg_name`
- Добавить `quality_state` параметр в API-вызовы
- Импорт из `shared/api/stock.ts`

### 3.5. Frontend — кнопка на `SpgSnapshotPage.tsx`

```typescript
// В state:
const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
const [importLocationId, setImportLocationId] = useState<number | null>(null);

// В шапке рядом с "Ручная операция":
<Button
  variant="outline"
  size="sm"
  onClick={() => {
    if (!importLocationId && sections.length > 0) {
      setImportLocationId(sections[0].id);
    }
    setIsImportDialogOpen(true);
  }}
>
  Импорт из Excel
</Button>

// В конце JSX:
<ImportRemaindersDialog
  open={isImportDialogOpen}
  onOpenChange={setIsImportDialogOpen}
  locationId={importLocationId}
  onSaved={() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
  }}
/>
```

---

## 4. Тесты

### 4.1. Backend — `backend/tests/test_stock_remainder_import.py`

5-7 тестов:
1. `test_preview_remainders_excel_happy_path` — загрузка шаблона с 3 строками
2. `test_import_remainders_excel_creates_manual_in_transactions` — happy path,
   проверка StockTransaction (reason=MANUAL_IN), StockBalance обновлён
3. `test_import_remainders_excel_skip_invalid` — 1 валидная + 1 невалидная (нет SKU)
4. `test_import_remainders_excel_atomic_fail` — skip_invalid=False, есть ошибки →
   `success: false`, ничего не создано
5. `test_import_remainders_excel_clear_existing` — есть остатки, clear_existing=True →
   сначала `ADJUSTMENT_OUT` под ноль, потом `MANUAL_IN` новых
6. `test_import_remainders_excel_quality_state` — quality_state=SCRAP →
   StockBalance по (product, location, SCRAP)
7. `test_import_remainders_excel_idempotency` — повторный импорт с тем же
   idempotency_key → дубль не создаётся (опционально)

### 4.2. Frontend

Smoke-тест ручной: загрузить Excel → preview → применить → проверить таблицу
`StockBalancesPanel`.

---

## 5. Файлы

### Новые
- `backend/app/stock/import_service.py`
- `backend/tests/test_stock_remainder_import.py`
- `frontend/src/features/spg/components/ImportRemaindersDialog.tsx`

### Изменяемые
- `backend/app/stock/api.py` — добавить 3 endpoint'а
- `backend/app/stock/__init__.py` — экспорт `parse_remainders_excel`,
  `apply_remainders_import` (опционально)
- `frontend/src/shared/api/stock.ts` — добавить функции
- `frontend/src/features/spg/pages/SpgSnapshotPage.tsx` — добавить кнопку

### Не трогаем
- `backend/app/stock/services.py` — `StockCommandService.record()` уже умеет
  всё что нужно
- `backend/app/services/excel_import.py` — `parse_row_selection` переиспользуем
- `backend/app/services/excel_templates.py` — `generate_remainders_excel_template`
  переиспользуем

---

## 6. Коммит

Один коммит: `feat(spg): вернуть импорт остатков на странице ГХП (новая логика Stock Ledger)`.
