# Нормальная и сырьевая длины Implementation Plan

> **Для agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести учёт длин на единый реестр нормальных длин и использовать сырьевую длину только в автоматическом расчёте подвесов.

**Architecture:** `ProductLength` становится единственным реестром длин линейного артикула; каждая запись получает необязательное поле `raw_length_mm` и вычисляемую эффективную сырьевую длину. План, остатки, задания, передачи, ledger и пила продолжают хранить только нормальную длину. План импорта фиксирует рассчитанный снимок `N`, а live-таблица подвесов получает эффективную сырьевую длину из карточки. Старая ADR-0024 заменяется чистым переходом без автоматического преобразования 2750.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, PostgreSQL 15; React 18.3, TypeScript, TanStack Query, Vitest.

**Spec:** `docs/adr/0028-normalnaya-i-syrevaa-dlina-podvesa.md`, `CONTEXT.md`.

## Global Constraints

- Backend-операции с БД выполняются только через `AsyncSession`.
- `raw_length_mm` — first-class nullable-поле каждой `ProductLength`; `raw_length_mm >= length_mm`, `raw_length_mm IS NULL` означает fallback на `length_mm`.
- Raw применяется только к линейным артикулам (`dimension_state = length`) и только к авторасчёту/отображению подвеса.
- В `dimensions`, плане, складе, WorkTask, Transfer, StockTransaction и раскрое нельзя записывать raw.
- Ручное `quantity_per_hanger` остаётся ключом нормальной длины; изменение raw не удаляет ручное значение.
- Для пары кандидаты — пересечение нормальных длин; auto запрещён для конкретной длины при неравных effective raw, manual для этой длины продолжает работать.
- Импорт плана не подставляет «ближайшую сверху» длину; неизвестная нормальная длина делает ошибкой только затронутую позицию.
- Старые планы версии 1 доступны только для чтения до переимпорта; старые остатки переоцениваются штатными операциями; автоматическая конвертация 2750 запрещена.
- Excel-формат каталога сохраняет отсутствие raw-колонки отдельно от явного пустого сегмента и проверяет позиционное число сегментов.
- Не изменять чужие незакоммиченные файлы; существующий WIP `frontend/e2e/sawing-four-lengths-cycle.spec.ts` не трогать без разрешения владельца.
- Перед каждым прогоном pytest использовать `scripts/test-run.ps1` через `npm run test:pytest`; при параллельной работе задать `PYTEST_NUM_WORKERS=4`.
- Коммиты, если работа выполняется отдельным исполнителем, только точечные по своим файлам; `git add .` запрещён.

---

## File Map

**Create:**

- `backend/alembic/versions/059_product_length_raw_length.py` — колонка, ограничение и перенос legacy scalar.
- `backend/alembic/versions/060_length_model_cutover.py` — флаг версии плана и удаление runtime-зависимости от linear legacy fields после preflight.
- `backend/tests/test_product_length_raw.py` — API/ORM validation, fallback, очистка raw и миграционные контракты.
- `backend/tests/test_plan_length_cutover.py` — нормальные dimensions плана, позиционные ошибки и snapshot `N`.
- `backend/tests/test_hanger_raw_lengths.py` — single/pair effective raw, manual-mode и per-length mismatch.

**Modify backend:**

- `backend/app/models/product.py`
- `backend/app/api/routes/products.py`
- `backend/app/services/catalog_excel_import.py`
- `backend/app/api/routes/catalog_import.py`
- `backend/app/services/product_pair_resolver.py`
- `backend/app/services/plan_position_hanger.py`
- `backend/app/services/plan_import_service.py`
- `backend/app/models/production_plan.py`
- `backend/app/api/routes/production_plans.py`
- `backend/app/api/routes/imports.py`
- `backend/app/services/production_plan_service.py`
- `backend/tests/test_products_hanger_auto.py`
- `backend/tests/test_product_pairs.py`
- `backend/tests/test_plan_import_codes.py`
- `backend/tests/test_plan_position_hanger.py`
- `backend/tests/test_hanger_calc_api.py`
- `backend/tests/test_catalog_excel_import.py`

**Modify frontend:**

- `frontend/src/shared/api/products.ts`
- `frontend/src/shared/lib/hangerQuantity.ts`
- `frontend/src/features/references/lib/hangerCalcRows.ts`
- `frontend/src/features/references/components/CatalogForm.tsx`
- `frontend/src/features/references/components/CatalogCard.tsx`
- `frontend/src/features/references/components/HangerCalcTable.tsx`
- `frontend/src/features/references/components/HangerCalcRowView.tsx`
- `frontend/src/features/references/components/PairedHangerRowView.tsx`
- `frontend/src/features/references/pages/RawMaterialsPage.tsx`
- `frontend/src/features/references/lib/hangerCalcRows.test.ts`
- `frontend/src/shared/lib/hangerQuantity.test.ts`
- `frontend/src/features/references/pages/RawMaterialsPage.test.tsx`
**Modify docs:**

- `docs/catalog-excel-format.md` — обновлённый параллельный формат сырьевых длин.

---

### Task 1: ProductLength data model and product API

**Files:**

- Create: `backend/alembic/versions/059_product_length_raw_length.py`
- Create: `backend/tests/test_product_length_raw.py`
- Modify: `backend/app/models/product.py:372-391`
- Modify: `backend/app/api/routes/products.py:109-170, 201-234, 321-420, 901-1100`

**Interfaces:**

```python
class ProductLengthIn(BaseModel):
    length_mm: float
    raw_length_mm: float | None = None
    is_primary: bool = False

class ProductLengthOut(BaseModel):
    length_mm: float
    raw_length_mm: float | None
    is_primary: bool
```

`ProductIn`/`ProductPatch` receive `lengths: list[ProductLengthIn]` for linear articles. `ProductOut.lengths` is the canonical list; the runtime API for linear articles no longer accepts or returns the old scalar `length_mm`, `lengths_mm`, or `primary_length_mm`. Non-linear `dimensions` remain unchanged.

- [ ] **Step 1: Write failing ORM/API tests**

Add tests for:

```python
async def test_create_linear_product_with_raw_length(client, session):
    response = await client.post(
        "/api/products",
        json={
            "sku": "RAW-2700",
            "name": "Профиль",
            "type": "component",
            "lengths": [{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
        },
    )
    assert response.status_code == 201
    assert response.json()["lengths"] == [
        {"length_mm": 2700.0, "raw_length_mm": 2750.0, "is_primary": True}
    ]
```

Also assert HTTP 422 for `raw_length_mm=2699`, duplicate normal lengths, multiple primary lengths, and raw values on `dimension_state in {area, volume}`. Add a patch test proving `raw_length_mm` omitted leaves the existing value and a normal-length change above explicit raw clears that raw value.

- [ ] **Step 2: Run the focused tests and verify red**

Run from the repository root:

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "product_length_raw"
```

Expected: the new tests fail because `raw_length_mm` and the `lengths` DTO do not exist.

- [ ] **Step 3: Add the migration**

Create revision `059_product_length_raw_length` with `down_revision = "058_product_pair_quantity_norms"`. Add `raw_length_mm FLOAT NULL` to `product_lengths` and a check constraint equivalent to:

```sql
CHECK (raw_length_mm IS NULL OR raw_length_mm >= length_mm)
```

Переносить старый scalar только для продуктов без строк `ProductLength`: вставить `(product_id, length_mm, is_primary=true, raw_length_mm=NULL)`. Существующие строки реестра не перезаписывать, а сохранённое 2750 автоматически не преобразовывать. Миграция должна быть идемпотентной; downgrade удаляет только новую колонку и ограничение.
Перед удалением runtime-зависимости от `product_dimensions.default_value`
выполнить preflight и собрать все линейные артикулы, у которых типовой размер
не совпадает с основной нормальной длиной. Совпадающие значения можно удалить
cleanup-миграцией; конфликтующие значения не менять автоматически — они блокируют
финальную очистку до ручного разрешения оператором. Миграция не имеет права выбирать
2700 для сохранённого 2750.

- [ ] **Step 4: Implement the model and pure validation helpers**

Add `ProductLength.raw_length_mm` and:

```python
@property
def effective_raw_length_mm(self) -> float:
    return self.raw_length_mm if self.raw_length_mm is not None else self.length_mm
```

Add a pure validator in `products.py` that enforces positive finite values, uniqueness of `length_mm`, at most/exactly one primary length for a linear product, and `raw_length_mm >= length_mm`. Clearing logic belongs in the same validator: when a normal length increases above an explicit raw, set that row's raw to `None` before persistence.

- [ ] **Step 5: Replace linear product input/output plumbing**

Update `ProductIn`, `ProductPatch`, `ProductOut`, `_to_product_out`, `create_product`, `patch_product`, `_sync_lengths`, and `_set_primary_length` to use the canonical `lengths` list. Remove runtime reads/writes of the legacy linear scalar fields after the migration backfill. Keep `dimensions` handling for `area`/`volume` products unchanged.

- [ ] **Step 6: Run focused backend tests**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "product_length_raw or products_hanger_auto or products_list"
```

Expected: all selected tests pass, including the pre-existing hanger tests after their DTO fixtures are migrated to `lengths`.

- [ ] **Step 7: Commit the isolated model/API slice**

```bash
git add backend/alembic/versions/059_product_length_raw_length.py backend/app/models/product.py backend/app/api/routes/products.py backend/tests/test_product_length_raw.py backend/tests/test_products_hanger_auto.py
git commit -m "feat: добавить сырьевую длину к реестру длин"
```

---

### Task 2: Excel-каталог: round-trip и очистка legacy

**Files:**

- Modify: `docs/catalog-excel-format.md`
- Modify: `backend/app/services/catalog_excel_import.py:18-66, 121-270, 277-399, 313-345, 351-430`
- Modify: `backend/app/api/routes/catalog_import.py` where parsed rows are applied/exported.
- Modify: `backend/tests/test_catalog_excel_import.py`
- Modify: `backend/tests/test_products_hanger_auto.py` for the scalar migration cases.

**Interfaces:**

```python
@dataclass(slots=True)
class ParsedCatalogRow:
    fields: dict[str, Any]
    # raw_lengths_mm отсутствует, если колонки нет;
    # raw_lengths_mm=[None, 2750], если колонка есть, а первый сегмент пуст.
```

- [ ] **Step 1: Add failing Excel tests**

Cover these exact cases:

```python
async def test_catalog_excel_raw_lengths_round_trip(...):
    # Длины, мм: 2700, 3000
    # Сырьевые длины, мм: 2750, [empty]
```

Проверить, что экспорт содержит колонку `Сырьевые длины, мм`, сохраняет пустой второй сегмент и различает `raw_length_mm=None` от явного `raw_length_mm=2700`. Добавить ошибку при несовпадении числа сегментов и тест частичного обновления: отсутствующая raw-колонка сохраняет значения, присутствующая заменяет список целиком.

- [ ] **Step 2: Run the focused Excel tests and verify red**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "catalog_excel"
```

Expected: new tests fail because the header, parser field, and exporter do not exist.

- [ ] **Step 3: Add the parallel Excel column**

Add `Сырьевые длины, мм` to `TEMPLATE_HEADERS` and `_HEADER_FIELDS` under the internal key `raw_lengths_mm`. Parse comma-separated segments with the existing number parser; an empty segment becomes `None`. If the column is present, require `len(raw_lengths_mm) == len(lengths_mm)` and validate each explicit raw against its normal length. If the column is absent, leave the key absent so apply logic can preserve existing values.

- [ ] **Step 4: Update apply/diff/export semantics**

In `diff_catalog_row` and the catalog apply route:

- absent `raw_lengths_mm` → preserve existing rows;
- present list → replace the complete raw mapping by normal length;
- blank segment → store SQL `NULL`, not the normal value;
- remove raw values when the corresponding normal length is removed;
- reject raw values for sheet/volume rows.

In the exporter, write a scalar for one raw value and a comma-separated list with empty segments for multiple values, mirroring `format_lengths_cell` and `format_quantities_cell`.

- [ ] **Step 5: Document the format and migration behavior**

Extend `docs/catalog-excel-format.md` with a worked `2700, 3000` / `2750, [empty]` example, partial-update rules, and the rule that `2750` is not auto-converted. State that sheets do not have a raw-length column.

- [ ] **Step 6: Run the catalog test slice**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "catalog_excel or products_hanger_auto"
```

Expected: all catalog import/export, round-trip, and legacy scalar tests pass.

- [ ] **Step 7: Commit the catalog slice**

```bash
git add backend/app/services/catalog_excel_import.py backend/app/api/routes/catalog_import.py backend/tests/test_catalog_excel_import.py docs/catalog-excel-format.md
 git commit -m "feat: перенести сырьевые длины в Excel справочника"
```

---

### Task 3: Расчёт подвеса и семантика пар

**Files:**

- Create: `backend/tests/test_hanger_raw_lengths.py`
- Modify: `backend/app/services/product_pair_resolver.py:64-282`
- Modify: `backend/app/services/plan_position_hanger.py:138-316`
- Modify: `backend/tests/test_product_pairs.py`
- Modify: `backend/tests/test_plan_position_hanger.py`
- Modify: `backend/tests/test_hanger_calc_api.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class PairLengthCandidate:
    length_mm: float
    raw_length_a_mm: float
    raw_length_b_mm: float

async def pair_length_candidates(
    db: AsyncSession, resolved: ResolvedPair
) -> list[PairLengthCandidate]: ...
```

`resolve_pair_n` получает нормальный `length_mm`, сравнивает effective raw A/B кандидата только для auto-формулы и возвращает `calc_error=True` при несовпадении. Положительный manual override разрешается до проверки несовпадения и остаётся действительным.

- [ ] **Step 1: Write failing calculation tests**

Add cases for:

```python
# one profile: normal=2700, raw=2750 -> compute area with 2750
# raw=None -> compute area with 2700
# pair: both normal=2700, both raw=2750 -> auto works
# pair: raw A=2750, raw B=2700 -> auto unavailable for 2700
# same mismatch with manual N -> manual N returned
```

Assert the by-size branch remains unchanged and the normal-length key remains the key used for `quantity_per_hanger`.

- [ ] **Step 2: Run the focused calculation tests and verify red**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "hanger_raw_lengths or product_pairs or plan_position_hanger"
```

Ожидаемый результат: тесты падают, потому что кандидаты пары не несут raw, а single-резолвер передаёт в формулу нормальную длину.

- [ ] **Step 3: Implement effective raw resolution**

Использовать `ProductLength.effective_raw_length_mm` для одиночных артикулов. Загрузчик кандидатов пары должен возвращать по одному `PairLengthCandidate` на общую нормальную длину с effective raw A и B. Ручной поиск и идентичность длины пары остаются по `length_mm`.

- [ ] **Step 4: Enforce the pair rule**

Для каждой общей нормальной длины сравнить effective raw A/B до auto-расчёта. При неравенстве вернуть ошибку только для этой длины; не запрещать другие длины пары и не менять ручные значения. Сохранить текущую арифметику `by_size` и округление вниз.

- [ ] **Step 5: Run calculation and API tests**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "hanger_raw_lengths or hanger_calc_api or product_pairs or plan_position_hanger"
```

Expected: all selected tests pass and existing size-limit behavior is unchanged.

- [ ] **Step 6: Commit the calculation slice**

```bash
git add backend/app/services/product_pair_resolver.py backend/app/services/plan_position_hanger.py backend/tests/test_hanger_raw_lengths.py backend/tests/test_product_pairs.py backend/tests/test_plan_position_hanger.py backend/tests/test_hanger_calc_api.py
 git commit -m "feat: считать подвесы по сырьевой длине"
```

---

### Task 4: Переход импорта плана и неизменяемый снимок N

**Files:**

- Create: `backend/alembic/versions/060_length_model_cutover.py`
- Create: `backend/tests/test_plan_length_cutover.py`
- Modify: `backend/app/models/production_plan.py:85-100`
- Modify: `backend/app/services/plan_import_service.py:45-220, 524-910`
- Modify: `backend/app/api/routes/imports.py`, `backend/app/api/routes/production_plans.py`, and `backend/app/services/production_plan_service.py` for the read-only guard.
- Modify: `backend/tests/test_plan_import_codes.py`, `backend/tests/test_single_row_plan_import.py`, `backend/tests/test_plan_position_dimensions.py`.

**Interfaces:**

```python
LENGTH_MODEL_VERSION_CURRENT = 2
LENGTH_MODEL_VERSION_LEGACY = 1
```

`ProductionPlan.length_model_version` — non-null поле со значением `2` для новых планов. Существующие строки получают `1`. План версии `1` доступен для чтения, но его нельзя применить, подтвердить, выпустить или передать в новый shopfloor; его нужно переимпортировать.

- [ ] **Step 1: Write failing plan tests**

Add tests for:

```python
async def test_plan_import_keeps_normal_input_dimensions(...):
    # Excel input 2700, catalog raw 2750
    # PlanPosition.input_dimensions == {"length_mm": 2700}
    # WorkTask/ledger consumers see 2700
```

Also assert:

- no `raw_length_substituted` warning and no `raw_length_not_found` code;
- a position with an unregistered normal length is `invalid`/errored while another position in the same file remains importable;
- `after_data["quantity_per_hanger"]` is the snapshot resolved with raw at import;
- changing `raw_length_mm` after import does not change the stored snapshot;
- a version-1 plan can be fetched but its mutating endpoints return a clear read-only error.

- [ ] **Step 2: Run the plan tests and verify red**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "plan_length_cutover or plan_import_codes or plan_position_dimensions"
```

Ожидаемый результат: тесты падают, потому что материализация raw и legacy-scalar-планирование ещё активны.

- [ ] **Step 3: Add the plan version migration**

Создать `060_length_model_cutover` с `down_revision = "059_product_length_raw_length"`. Добавить `length_model_version INTEGER NOT NULL` в `production_plans`, значение `2` для новых строк и backfill `1` для существующих. Индекс в этой миграции не добавлять: существующих primary-key и status-путей достаточно.

- [ ] **Step 4: Remove raw materialization from import**

Удалить `_pick_raw_length_mm`, `_materialize_raw_length_mm`, `_load_raw_lengths_mm`, silent-подстановку и коды `raw_length_substituted`/`raw_length_not_found`. Длину входа из Excel оставить без изменений. Разрешать `N` по строке нормальной длины и её effective raw, затем записывать `N` и источник в `PlanChangeItem.after_data` как неизменяемый снимок импорта.

- [ ] **Step 5: Add strict per-position errors and legacy read-only guard**

Если нормальная длина отсутствует в реестре, отметить только этот change item как invalid с `normal_length_not_found`; не выбирать соседнюю длину и не прерывать остальные строки. Перед apply/approve/release/shopfloor-мутациями проверять `length_model_version == LENGTH_MODEL_VERSION_CURRENT`; для версии `1` возвращать стабильную ошибку `legacy_plan_read_only`. Read/list/detail оставить доступными для аудита и переимпорта.

- [ ] **Step 6: Run plan and shopfloor tests**

```bash
PYTEST_NUM_WORKERS=4 npm run test:pytest -- -k "plan_length_cutover or plan_import_codes or plan_position_dimensions or shopfloor"
```

Ожидаемый результат: в plan/task/ledger попадают только нормальные размеры; старые планы читаются, но не изменяются.

- [ ] **Step 7: Commit the plan cutover slice**

```bash
git add backend/alembic/versions/060_length_model_cutover.py backend/app/models/production_plan.py backend/app/services/plan_import_service.py backend/app/api/routes/imports.py backend/app/api/routes/production_plans.py backend/tests/test_plan_length_cutover.py backend/tests/test_plan_import_codes.py backend/tests/test_single_row_plan_import.py backend/tests/test_plan_position_dimensions.py
 git commit -m "feat: убрать материализацию сырьевой длины из плана"
```

---

### Task 5: Каталог и экраны подвесов во frontend

**Files:**

- Modify: `frontend/src/shared/api/products.ts:27-110`
- Modify: `frontend/src/shared/lib/hangerQuantity.ts:78-167`
- Modify: `frontend/src/features/references/lib/hangerCalcRows.ts:22-330`
- Modify: `frontend/src/features/references/components/CatalogForm.tsx:222-420` and the length controls in the JSX.
- Modify: `frontend/src/features/references/components/CatalogCard.tsx`
- Modify: `frontend/src/features/references/components/HangerCalcTable.tsx:42-430`
- Modify: `frontend/src/features/references/components/HangerCalcRowView.tsx`
- Modify: `frontend/src/features/references/components/PairedHangerRowView.tsx`
- Modify: `frontend/src/features/references/pages/RawMaterialsPage.tsx`
- Modify: `frontend/src/features/references/lib/hangerCalcRows.test.ts`
- Modify: `frontend/src/shared/lib/hangerQuantity.test.ts`
- Modify: `frontend/src/features/references/pages/RawMaterialsPage.test.tsx`

**Interfaces:**

```ts
export type ProductLength = {
  length_mm: number;
  raw_length_mm: number | null;
  is_primary: boolean;
};

export function effectiveRawLength(length: ProductLength): number {
  return length.raw_length_mm ?? length.length_mm;
}
```

`HangerCalcRow` carries both the normal length and effective raw length. Calculation request refs remain keyed by normal length; only the numeric `length_mm` sent to the formula is effective raw. Search predicates match either normal or raw length.

- [ ] **Step 1: Write failing frontend tests**

Add unit tests for:

```ts
expect(effectiveRawLength({ length_mm: 2700, raw_length_mm: null, is_primary: true })).toBe(2700);
expect(effectiveRawLength({ length_mm: 2700, raw_length_mm: 2750, is_primary: true })).toBe(2750);
```

Add a `CatalogForm` test that edits raw 2750 for normal 2700, saves the canonical `lengths` payload, and leaves a manual `N` keyed by 2700 unchanged. Add a hanger row test asserting both `2700` and `2750` are visible, and a search test asserting either value finds the row.

- [ ] **Step 2: Run the focused Vitest files and verify red**

```bash
npm --prefix frontend run test -- --run src/shared/lib/hangerQuantity.test.ts src/features/references/lib/hangerCalcRows.test.ts src/features/references/pages/RawMaterialsPage.test.tsx
```

Expected: new tests fail because DTOs and rows still contain only normal lengths.

- [ ] **Step 3: Replace frontend product length DTOs and helpers**

Change `Product`, create/patch payloads, and all `productLengths`/`primaryLength` consumers to use `ProductLength[]` and `is_primary`. Remove linear-only legacy scalar fields from frontend types and form synchronization. Add `effectiveRawLength` and use it only in hanger calculation payload construction and hanger-specific display.

- [ ] **Step 4: Update CatalogForm length editing**

Replace the scalar `newLength`/parallel list state with a row editor containing normal length, optional raw length, and primary selection. A blank raw input remains `null`; an explicit value equal to normal remains numeric. On normal increase above an explicit raw, clear the raw input. Manual N controls remain keyed by the normal-length row.

- [ ] **Step 5: Update live hanger calculation and display**

In `buildCalcItems`/`buildPairedCalcItems`, map each normal length to its effective raw for the API request, while retaining normal length as the result/ref key. In row views, always render both normal and raw values, including `2700 / 2700` when raw is absent. In `HangerCalcTable`, make the search predicate match either value; keep ordinary catalog and plan displays on normal lengths only.

- [ ] **Step 6: Run focused frontend tests and build**

```bash
npm --prefix frontend run test -- --run src/shared/lib/hangerQuantity.test.ts src/features/references/lib/hangerCalcRows.test.ts src/features/references/pages/RawMaterialsPage.test.tsx
npm --prefix frontend run build
```

Expected: all selected Vitest tests pass and TypeScript/Vite build succeeds.

- [ ] **Step 7: Commit the frontend slice**

```bash
git add frontend/src/shared/api/products.ts frontend/src/shared/lib/hangerQuantity.ts frontend/src/features/references/lib/hangerCalcRows.ts frontend/src/features/references/components/CatalogForm.tsx frontend/src/features/references/components/CatalogCard.tsx frontend/src/features/references/components/HangerCalcTable.tsx frontend/src/features/references/components/HangerCalcRowView.tsx frontend/src/features/references/components/PairedHangerRowView.tsx frontend/src/features/references/pages/RawMaterialsPage.tsx frontend/src/shared/lib/hangerQuantity.test.ts frontend/src/features/references/lib/hangerCalcRows.test.ts frontend/src/features/references/pages/RawMaterialsPage.test.tsx
 git commit -m "feat: показать сырьевую длину в расчёте подвесов"
```

---

### Task 6: Удаление legacy runtime-путей, документация и полная проверка

**Files:**

- Modify: `backend/app/services/plan_import_service.py` и конкретные callers, которые покажет `npx @colbymchenry/codegraph sync` после Tasks 1–5.
- Modify: `backend/app/api/routes/products.py`, `backend/app/services/catalog_excel_import.py` и frontend-файлы, где после Tasks 1–5 ещё остались `lengths_mm`, `primary_length_mm` или линейный `length_mm`.
- Modify: `docs/project-overview.md`, `docs/catalog-excel-format.md`, `docs/plan-import-spec.md` и `docs/context-index.md` только в изменённых контрактах.
- Keep: `docs/adr/0024-dlina-gp-v-plane-podbor-dliny-syrya-blizhayshee-sverhu.md` as historical text with its superseded status; do not maintain its implementation path.
- Do not touch: `frontend/e2e/sawing-four-lengths-cycle.spec.ts` while it remains foreign WIP.

- [ ] **Step 1: Run a static legacy-reference audit**

```bash
npx @colbymchenry/codegraph sync
```

Затем искать в изменённых исходниках `raw_length_substituted`, `raw_length_not_found`, `_materialize_raw_length_mm`, `RAW_LENGTH_SILENT_TOLERANCE_MM`, линейные `lengths_mm` и `primary_length_mm`. Каждый оставшийся hit должен быть нелинейным измерением, историческим ADR или явно сохранённым тестовым fixture; production-линейных callers остаться не должно.

- [ ] **Step 2: Update product and plan documentation**

Описать различие normal/raw, точный столбец Excel, правило равенства пары, позиционную ошибку импорта, read-only версии plan 1 и процедуру ручной переоценки остатков в существующих документах. Не создавать второй глоссарий для тех же терминов.

- [ ] **Step 3: Run the full backend verification**

```bash
npm run db:migrate
PYTEST_NUM_WORKERS=4 npm run test:pytest
```

Ожидаемый результат: миграции применяются, все backend-тесты проходят, включая integrity ledger и новые тесты raw/plan.

- [ ] **Step 4: Run the full frontend verification**

```bash
npm --prefix frontend run test
npm --prefix frontend run build
```

Ожидаемый результат: все Vitest-наборы проходят, production build успешен.

- [ ] **Step 5: Exercise the actual changed surface**

Использовать уже запущенный стек проекта: открыть страницу сырья, создать/изменить линейный артикул с normal 2700 и raw 2750, проверить обе длины в таблице подвесов и расчёт по raw, затем очистить raw и проверить fallback на 2700. Импортировать план с 2700 и проверить, что размер плана, задания и shopfloor остаётся 2700. Не использовать business API для E2E-проверок и не перезапускать пользовательский стек.

- [ ] **Step 6: Finalize the documentation and commits**

Выполнить:

```bash
npx @colbymchenry/codegraph sync
git diff --check
```

Коммитить только собственные файлы русским conventional-сообщением, например:

```bash
git commit -m "feat: завершить переход на нормальные длины"
```

Не добавлять, не откатывать, не stash-ить и не удалять чужие WIP-файлы.

---

## Self-review checklist

- [x] Каждое правило ADR-0028 имеет задачу: реестр/raw, fallback и валидация, равенство пары, normal-only plan/ledger, снимок, Excel, UI, миграция и read-only старые планы.
- [x] Ни одна задача не сохраняет материализацию ADR-0024 или dual-write совместимый путь.
- [x] `raw_length_mm` не попадает в `dimensions` или payload движений ledger.
- [x] Ручное N остаётся по нормальной длине и переживает изменение raw.
- [x] Несовпадение пары относится к конкретной длине и блокирует только auto-расчёт.
- [x] Excel различает отсутствующую raw-колонку и явно пустой сегмент.
- [x] Чужой WIP исключён из владения файлами и коммитов.
- [x] Команды backend, frontend, миграций и фактической UI-проверки указаны.
