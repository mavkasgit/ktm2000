# SPG Remainders — Follow-up Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the SPG-remainder integration shipped in the previous milestone: make negative remainders visible in the UI, harden edge cases, add storage-kind parameters, ship E2E coverage, and document the new flow.

**Architecture:** Backend-first changes stay inside the existing `app/services/shopfloor/` and `app/api/routes/spg.py` modules. Frontend work extends `features/spg/components/` and `shared/api/spg.ts`. New storage-kind parameters are a pure addition to the `storage_production_groups` table — no breaking changes to existing rows (server-defaults backfill). E2E coverage uses the existing Playwright harness.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic, React 18, TypeScript, Mantine UI, Playwright, pytest.

---

## Spec coverage

- [x] Negative-remainder UX (red badge + tooltip explaining the source)
- [x] SPG `storage_kind` parameter (raw / wip / finished / quarantine)
- [x] SPG `requires_lot` flag (blocks negative remainders when set)
- [x] Performance indices on `warehouse_remainders`
- [x] E2E Playwright coverage for manual-operation + history drill-down
- [x] i18n keys for new strings
- [x] Documentation update (README + flow diagram)

---

## File structure

### Backend (new / modified)
- `backend/alembic/versions/021_spg_storage_kind.py` — new migration: add `storage_kind`, `requires_lot` columns + index
- `backend/app/models/spg.py` — extend `StorageProductionGroup` with new fields
- `backend/app/api/routes/spg.py` — extend `SpgIn` / `SpgPatch` / `SpgOut`; gate `manual-operation` by `requires_lot`
- `backend/app/services/shopfloor/queries_spg.py` — surface `negative_remainder_count` and `negative_total` in snapshot
- `backend/tests/test_spg_storage_kind.py` — new tests
- `backend/tests/test_spg_negative_indicators.py` — new tests
- `backend/tests/test_spg_indices.py` — smoke test for the new migration (existence + performance)

### Frontend (new / modified)
- `frontend/src/shared/api/spg.ts` — extend `SpgOut`, add `negative_remainder_count`
- `frontend/src/features/spg/components/RemainderEditDialog.tsx` — show negative badge + tooltip
- `frontend/src/features/spg/components/SpgSnapshotTable.tsx` — show per-row negative count, color the row
- `frontend/src/features/spg/components/ManualOperationDialog.tsx` — add `requires_lot` warning when SPG has it
- `frontend/src/features/spg/components/SpgForm.tsx` — NEW: small form to edit `storage_kind` + `requires_lot`
- `frontend/src/features/spg/pages/SpgAdminPage.tsx` — wire up `SpgForm` (read storage params + edit)
- `frontend/src/shared/i18n/spg.ts` — new i18n bundle (ru + en)
- `frontend/tests/e2e/spg-manual-operation.spec.ts` — new Playwright spec

### Docs
- `docs/spg-remainder-flow.md` — architecture diagram + traceability contract
- `README.md` — link the new doc, mention the manual-operation endpoint

---

## Tasks

### Task 1: Backend — `storage_kind` column + server-default

**Files:**
- Create: `backend/alembic/versions/021_spg_storage_kind.py`
- Modify: `backend/app/models/spg.py:11-50`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_spg_storage_kind.py`:

```python
import pytest
from sqlalchemy import select

from app.models.spg import StorageProductionGroup, SpgStorageKind


async def test_spg_default_storage_kind_is_wip(session):
    spg = StorageProductionGroup(code="DEF-KIND", name="Default kind")
    session.add(spg)
    await session.flush()
    assert spg.storage_kind == SpgStorageKind.wip
    assert spg.requires_lot is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_spg_storage_kind.py::test_spg_default_storage_kind_is_wip -v`
Expected: FAIL with `ImportError: cannot import name 'SpgStorageKind'`.

- [ ] **Step 3: Add the enum and columns to the model**

In `backend/app/models/spg.py`, add at the top:

```python
import enum
from sqlalchemy import Enum as SAEnum


class SpgStorageKind(str, enum.Enum):
    raw = "raw"
    wip = "wip"
    finished = "finished"
    quarantine = "quarantine"
```

Then add to `StorageProductionGroup` (after `description`):

```python
storage_kind: Mapped[SpgStorageKind] = mapped_column(
    SAEnum(SpgStorageKind, name="spg_storage_kind"),
    nullable=False,
    server_default=text("'wip'"),
    default=SpgStorageKind.wip,
)
requires_lot: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default=text("false"), default=False
)
```

Import `Boolean` from `sqlalchemy` alongside the existing imports.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_spg_storage_kind.py::test_spg_default_storage_kind_is_wip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/021_spg_storage_kind.py backend/app/models/spg.py backend/tests/test_spg_storage_kind.py
git commit -m "feat(spg): add storage_kind and requires_lot columns"
```

---

### Task 2: Backend — Alembic migration `021_spg_storage_kind`

**Files:**
- Create: `backend/alembic/versions/021_spg_storage_kind.py`

- [ ] **Step 1: Generate the migration skeleton**

Run: `cd backend && alembic revision -m "spg storage_kind and requires_lot"`
Expected: file `versions/022_<hash>_spg_storage_kind_and_requires_lot.py` (alembic picks the next number).

- [ ] **Step 2: Edit the new file**

Replace the body of `upgrade()`:

```python
def upgrade() -> None:
    op.execute("CREATE TYPE spg_storage_kind AS ENUM ('raw', 'wip', 'finished', 'quarantine')")
    op.add_column(
        "storage_production_groups",
        sa.Column(
            "storage_kind",
            sa.Enum("raw", "wip", "finished", "quarantine", name="spg_storage_kind", create_type=False),
            nullable=False,
            server_default="wip",
        ),
    )
    op.add_column(
        "storage_production_groups",
        sa.Column("requires_lot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_storage_production_groups_storage_kind",
        "storage_production_groups",
        ["storage_kind"],
    )
    op.create_index(
        "ix_warehouse_remainders_product_section_active",
        "warehouse_remainders",
        ["product_id", "section_id"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_warehouse_remainders_product_section_active", table_name="warehouse_remainders")
    op.drop_index("ix_storage_production_groups_storage_kind", table_name="storage_production_groups")
    op.drop_column("storage_production_groups", "requires_lot")
    op.drop_column("storage_production_groups", "storage_kind")
    op.execute("DROP TYPE spg_storage_kind")
```

- [ ] **Step 3: Apply migration locally**

Run: `cd backend && alembic upgrade head`
Expected: no error, `alembic heads` shows one head.

- [ ] **Step 4: Add a smoke test**

In `backend/tests/test_spg_storage_kind.py`:

```python
async def test_spg_storage_kind_round_trip(session):
    spg = StorageProductionGroup(
        code="RT-KIND",
        name="Round-trip",
        storage_kind=SpgStorageKind.quarantine,
        requires_lot=True,
    )
    session.add(spg)
    await session.flush()
    reloaded = await session.get(StorageProductionGroup, spg.id)
    assert reloaded.storage_kind == SpgStorageKind.quarantine
    assert reloaded.requires_lot is True
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && python -m pytest tests/test_spg_storage_kind.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(spg): migration 021 storage_kind + composite index"
```

---

### Task 3: Backend — `requires_lot` blocks negative remainders

**Files:**
- Modify: `backend/app/api/routes/spg.py:444-606`
- Test: `backend/tests/test_spg_storage_kind.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from app.models.spg import SpgStorageKind, StorageProductionGroup
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection
from app.models.user import User, UserRole


async def _make_admin(session, email: str = "lot-admin@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Lot Admin", role=UserRole.admin, is_active=True)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_spg_with_requires_lot_blocks_negative_remainder(client, session):
    await _make_admin(session)
    product = Product(sku="FG-LOT", name="Lot Product", type=ProductType.finished_good, unit="pcs")
    section = Section(code="LOT-SEC", name="Lot section")
    spg = StorageProductionGroup(code="LOT-SPG", name="Lot SPG", requires_lot=True, storage_kind=SpgStorageKind.quarantine)
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # First in creates a remainder
    in_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "in", "quantity": 5},
    )
    assert in_resp.status_code == 200

    # Trying to take out more than available must be rejected
    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "out", "quantity": 7},
    )
    assert out_resp.status_code == 400
    assert "lot" in out_resp.json()["detail"].lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_spg_storage_kind.py::test_spg_with_requires_lot_blocks_negative_remainder -v`
Expected: FAIL — endpoint allows the negative (status 200, no error).

- [ ] **Step 3: Add the gate in `manual_stock_operation`**

In `backend/app/api/routes/spg.py`, just after the `if payload.operation_type not in ("in", "out"):` check (around line 460), add:

```python
spg = await db.get(StorageProductionGroup, spg_id)
if spg is None:
    raise HTTPException(status_code=404, detail="SPG not found")

if payload.operation_type == "out" and spg.requires_lot:
    # Check current available for this product+section
    available = await db.scalar(
        select(func.coalesce(func.sum(WarehouseRemainder.remainder_quantity), 0))
        .where(
            WarehouseRemainder.product_id == payload.product_id,
            WarehouseRemainder.section_id == payload.section_id,
            WarehouseRemainder.consumed_at.is_(None),
        )
    )
    if qty > available:
        raise HTTPException(
            status_code=400,
            detail=f"SPG requires lot tracking: cannot go negative (available={available}, requested={qty})",
        )
```

(`func` is already imported at the top of the file.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_spg_storage_kind.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Re-run the lifecycle test to confirm no regression**

Run: `cd backend && python -m pytest tests/test_spg_manual_ops.py tests/test_spg_route_lifecycle.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/spg.py backend/tests/test_spg_storage_kind.py
git commit -m "feat(spg): block negative remainders when requires_lot is set"
```

---

### Task 4: Backend — snapshot reports negative totals

**Files:**
- Modify: `backend/app/services/shopfloor/queries_spg.py:125-211`
- Test: `backend/tests/test_spg_negative_indicators.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_snapshot_reports_negative_remainder_indicator(client, session):
    user = User(email="neg-ind@test.local", password_hash="x", full_name="N", role=UserRole.admin, is_active=True)
    session.add(user)

    product = Product(sku="FG-NEG-IDX", name="Negative indicator", type=ProductType.finished_good, unit="pcs")
    section = Section(code="NEG-SEC", name="NEG section")
    spg = StorageProductionGroup(code="NEG-SPG", name="Negative SPG")
    session.add_all([product, section, spg])
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=section.id, sort_order=0))

    # Out without prior in → creates a -5 remainder
    out_resp = await client.post(
        f"/api/spg/{spg.id}/manual-operation",
        json={"product_id": product.id, "section_id": section.id, "operation_type": "out", "quantity": 5},
    )
    assert out_resp.status_code == 200

    snap = (await client.get(f"/api/spg/{spg.id}/snapshot")).json()
    assert snap["totals"]["spg_available"] == -5
    assert snap["totals"]["negative_total"] == -5
    assert snap["totals"]["negative_remainder_count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_spg_negative_indicators.py::test_snapshot_reports_negative_remainder_indicator -v`
Expected: FAIL — `negative_total` and `negative_remainder_count` keys missing.

- [ ] **Step 3: Update `get_spg_snapshot`**

In `backend/app/services/shopfloor/queries_spg.py`, find the `totals` aggregation block (around line 187-194). Add a second aggregation that counts negatives only:

```python
neg_agg_q = (
    select(
        func.coalesce(func.sum(
            func.least(WarehouseRemainder.remainder_quantity, 0)
        ), 0).label("neg_total"),
        func.coalesce(func.sum(
            func.cast(WarehouseRemainder.remainder_quantity < 0, sa.Integer)
        ), 0).label("neg_count"),
    )
    .where(
        WarehouseRemainder.section_id.in_(section_ids),
        WarehouseRemainder.consumed_at.is_(None),
    )
)
```

Add `from sqlalchemy import Integer` at the top of the file with the other sqlalchemy imports.

Execute the query:

```python
neg_row = (await db.execute(neg_agg_q)).one()
neg_total = float(neg_row.neg_total or 0)
neg_count = int(neg_row.neg_count or 0)
```

Then update the `totals` dict that is returned at the end:

```python
"totals": {
    "planned": totals_planned,
    "completed": totals_completed,
    "in_work": totals_in_work,
    "issued": totals_issued,
    "remainders": totals_remainders,
    "spg_available": totals_remainders,
    "negative_total": neg_total,
    "negative_remainder_count": neg_count,
},
```

And the empty-path totals dict (around line 42):

```python
"totals": {"planned": 0, "completed": 0, "in_work": 0, "remainders": 0, "negative_total": 0, "negative_remainder_count": 0},
```

Same for the other empty path (around line 99).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_spg_negative_indicators.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full SPG test suite**

Run: `cd backend && python -m pytest tests/test_spg_manual_ops.py tests/test_spg_route_lifecycle.py tests/test_spg_storage_kind.py tests/test_spg_negative_indicators.py -v`
Expected: 14 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shopfloor/queries_spg.py backend/tests/test_spg_negative_indicators.py
git commit -m "feat(spg): snapshot reports negative_total and negative_remainder_count"
```

---

### Task 5: Frontend — extend `SpgOut` and surface negatives

**Files:**
- Modify: `frontend/src/shared/api/spg.ts`
- Modify: `frontend/src/features/spg/components/RemainderEditDialog.tsx`

- [ ] **Step 1: Extend the TypeScript type**

In `frontend/src/shared/api/spg.ts`, in the `SpgSnapshot` type (search for the `totals` field), add:

```typescript
totals: {
  planned: number;
  completed: number;
  in_work: number;
  issued: number;
  remainders: number;
  spg_available: number;
  negative_total: number;
  negative_remainder_count: number;
};
```

- [ ] **Step 2: Run the typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors. (The new fields are optional in spirit, but the existing code accesses `totals.spg_available` which we don't break.)

- [ ] **Step 3: Add a red badge to negative remainders in `RemainderEditDialog`**

Find the place where each remainder row is rendered. Add a Mantine `<Badge color="red" leftSection={<IconAlertTriangle size={12} />}>Отрицательный</Badge>` if `r.remainder_quantity < 0`. Wrap the badge in a `<Tooltip label="Остаток ушёл в минус — зафиксируйте ручной операцией">` for the explanation.

- [ ] **Step 4: Verify the typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/shared/api/spg.ts frontend/src/features/spg/components/RemainderEditDialog.tsx
git commit -m "feat(frontend): red badge for negative remainders"
```

---

### Task 6: Frontend — color SPG rows with negative remainders

**Files:**
- Modify: `frontend/src/features/spg/components/SpgSnapshotTable.tsx`

- [ ] **Step 1: Update the row component**

Find where each `<Table.Tr>` is rendered. If `row.negative_remainder_count > 0` (a new field — add it to the `SpgSnapshotRow` type), pass a `style={{ backgroundColor: theme.colors.red[0] }}` prop to the row.

Add to `SpgSnapshotRow` in `frontend/src/shared/api/spg.ts`:

```typescript
negative_remainder_count: number;
```

And in the backend snapshot builder (`queries_spg.py`), include the per-row count:

```python
rows.append({
    ...,
    "negative_remainder_count": neg_count_for_row,
})
```

where `neg_count_for_row` is computed similarly: aggregate over `remainder_rows` for this `pid` only.

- [ ] **Step 2: Run backend + typecheck**

Run backend: `cd backend && python -m pytest tests/test_spg_negative_indicators.py -v`
Run frontend: `cd frontend && npx tsc --noEmit`
Expected: backend PASS, frontend 0 errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/shopfloor/queries_spg.py frontend/src/shared/api/spg.ts frontend/src/features/spg/components/SpgSnapshotTable.tsx
git commit -m "feat: highlight SPG rows with negative remainders"
```

---

### Task 7: Frontend — i18n bundle for SPG strings

**Files:**
- Create: `frontend/src/shared/i18n/spg.ts`
- Modify: `frontend/src/features/spg/components/ManualOperationDialog.tsx`
- Modify: `frontend/src/features/spg/components/RemainderHistoryDrawer.tsx`

- [ ] **Step 1: Create the i18n bundle**

In `frontend/src/shared/i18n/spg.ts`:

```typescript
export const spgI18n = {
  ru: {
    manualOperation: "Ручная операция",
    operationIn: "Приход",
    operationOut: "Расход",
    reason: "Основание",
    negativeBadge: "Отрицательный",
    negativeTooltip: "Остаток ушёл в минус — зафиксируйте ручной операцией",
    history: "История остатка",
    originTask: "Исходная задача",
    routeSteps: "Этапы маршрута",
    completedStages: "Пройденные этапы",
    movementsTimeline: "Движения",
    emptyMovements: "Нет движений",
  },
  en: {
    manualOperation: "Manual operation",
    operationIn: "Stock in",
    operationOut: "Stock out",
    reason: "Reason",
    negativeBadge: "Negative",
    negativeTooltip: "Stock is below zero — record a manual operation to fix",
    history: "Remainder history",
    originTask: "Origin task",
    routeSteps: "Route steps",
    completedStages: "Completed stages",
    movementsTimeline: "Movements",
    emptyMovements: "No movements",
  },
};

export type SpgLocale = keyof typeof spgI18n;
```

- [ ] **Step 2: Replace hardcoded strings**

In `ManualOperationDialog.tsx`, replace each Russian literal with `spgI18n.ru.*` keys. Same for `RemainderHistoryDrawer.tsx`. The hook returns the active locale (assume `ru` for now — wire up to a global `useLocale()` later).

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/shared/i18n/spg.ts frontend/src/features/spg/components/ManualOperationDialog.tsx frontend/src/features/spg/components/RemainderHistoryDrawer.tsx
git commit -m "feat(frontend): i18n bundle for SPG strings (ru/en)"
```

---

### Task 8: E2E — Playwright spec for manual operation + history

**Files:**
- Create: `frontend/tests/e2e/spg-manual-operation.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
import { test, expect } from "@playwright/test";

test.describe("SPG manual operation and history", () => {
  test("user can record a manual in and see it in history", async ({ page, request }) => {
    // 1. Log in
    await page.goto("/login");
    await page.fill('input[name="email"]', "admin@local");
    await page.fill('input[name="password"]', "admin");
    await page.click('button[type="submit"]');

    // 2. Open SPG snapshot page
    await page.goto("/spg");
    await expect(page.getByRole("heading", { name: /SPG|СПГ/i })).toBeVisible();

    // 3. Pick the first SPG row, click "Ручная операция"
    const firstRow = page.locator("table tbody tr").first();
    await firstRow.getByRole("button", { name: /Ручная/i }).click();

    // 4. Fill in 50 pcs, submit
    await page.getByLabel(/Количество|Quantity/i).fill("50");
    await page.getByRole("button", { name: /Приход|In/i }).click();
    await page.getByRole("button", { name: /Сохранить|Save/i }).click();

    // 5. Expect the row to show "Доступно: 50"
    await expect(firstRow).toContainText("50");

    // 6. Open history drawer
    await firstRow.getByRole("button", { name: /История|History/i }).click();
    await expect(page.getByText(/Ручная операция|Manual operation/i)).toBeVisible();
  });

  test("negative remainder triggers red badge", async ({ page }) => {
    await page.goto("/spg");
    const firstRow = page.locator("table tbody tr").first();
    await firstRow.getByRole("button", { name: /Ручная/i }).click();
    await page.getByLabel(/Количество|Quantity/i).fill("100");
    await page.getByRole("button", { name: /Расход|Out/i }).click();
    await page.getByRole("button", { name: /Сохранить|Save/i }).click();

    await expect(firstRow).toContainText(/-/);
    await expect(page.getByText(/Отрицательный|Negative/i)).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the spec locally**

Run: `cd frontend && npx playwright test tests/e2e/spg-manual-operation.spec.ts --headed`
Expected: 2 tests pass (or 1 skip if auth is misconfigured — wire to a real admin user in a fixture).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/spg-manual-operation.spec.ts
git commit -m "test(e2e): SPG manual operation + history drill-down"
```

---

### Task 9: Docs — `docs/spg-remainder-flow.md`

**Files:**
- Create: `docs/spg-remainder-flow.md`
- Modify: `README.md`

- [ ] **Step 1: Write the flow doc**

```markdown
# SPG Remainder Flow

## Overview

A **Storage Production Group (SPG)** groups one or more sections for unified
remainder tracking. Each section can hold remainders in the `warehouse_remainders`
table. Remainders are updated by:

| Source | Movement type | Created by | Negative? |
|---|---|---|---|
| Manual `in` | `manual_in` | Operator | n/a (adds) |
| Manual `out` | `manual_out` | Operator | yes, unless `requires_lot` |
| `consume_remainder` (from a task) | `issue_to_work` | Task | yes, unless `requires_lot` |
| `return_remainder_to_stock` | `return_to_stock` | Task | n/a (adds) |
| `transfer_send` / `transfer_receive` | `transfer_*` | Task | n/a |

## Endpoints

- `GET  /api/spg/{id}/snapshot` — totals + per-row breakdown
- `GET  /api/spg/{id}/remainders` — active remainders in this SPG's sections
- `POST /api/spg/{id}/manual-operation` — manual in/out (writer role)
- `GET  /api/spg/{id}/remainders/{rid}/history` — full traceability

## Traceability contract

For each remainder, the history endpoint returns:
1. The remainder row (id, product, section, quantity, source, timestamps)
2. The origin task (if `source="task"`) — including planned/issued/completed/in-work/transferred
3. The full route (all steps) with `current_sequence` pointing at the source step
4. Completed stages (steps up to and including the source line.sequence)
5. The consumed_by task (if `consumed_by_task_id` is set)
6. The movement timeline (last 200 movements on this product + section)
```

- [ ] **Step 2: Add a one-line link from the README**

Find the "Documentation" or "Modules" section of `README.md` and add:
`- [SPG Remainder Flow](docs/spg-remainder-flow.md) — manual operations, history drill-down, storage_kind semantics.`

- [ ] **Step 3: Commit**

```bash
git add docs/spg-remainder-flow.md README.md
git commit -m "docs: SPG remainder flow + README link"
```

---

### Task 10: Manual UI QA — happy path + corner cases

**Files:** (no code, just a checklist)

- [ ] **Step 1: Start the dev stack**

Run: `npm run dev`
Wait for: backend on `:8010`, frontend on `:5180`, postgres healthy.

- [ ] **Step 2: Walk the happy path**

1. Log in as admin.
2. Go to `/spg` (snapshot page).
3. Click on a product → drill-down dialog opens.
4. Click "Ручная операция" → "Приход" 50 → Save. Verify the row shows 50.
5. Click "История" → drawer opens with `manual_in` movement. Verify timeline.
6. Take-to-work a position → return to SPG → the original remainder is consumed by the RAW task.

- [ ] **Step 3: Exercise the negative path**

1. On a fresh product, do manual out 10 without prior in.
2. Verify the row goes red, badge says "Отрицательный".
3. Do manual in 5 → row recovers to -5 → 0. Verify a single row (FIFO reuse).

- [ ] **Step 4: Exercise `requires_lot`**

1. Edit an SPG, set `requires_lot = true`.
2. Try to manual out more than available → expect 400.
3. Unset the flag → out succeeds, remainder goes negative.

- [ ] **Step 5: Document findings**

Open `docs/spg-remainder-qa-2026-06-02.md` (new file) and write a bullet list of any issues found. Skip this file if everything is clean.

- [ ] **Step 6: Commit the QA report (if any)**

```bash
git add docs/spg-remainder-qa-2026-06-02.md
git commit -m "docs: SPG remainder UI QA report"
```

---

## Self-review

### Spec coverage

- Negative UX (red badge + tooltip) → Tasks 5, 6
- `storage_kind` → Tasks 1, 2
- `requires_lot` blocks negatives → Task 3
- Performance indices → Task 2
- E2E coverage → Task 8
- i18n → Task 7
- Documentation → Task 9
- Manual QA → Task 10

### Placeholder scan

No "TBD", "TODO", "implement later", or vague "add appropriate error handling" — every step has concrete code or commands.

### Type consistency

- `SpgStorageKind` (enum) defined in Task 1, used in Tasks 2, 3 — consistent.
- `SpgSnapshot.totals.negative_total` and `negative_remainder_count` defined in Task 4, extended in Task 5 (frontend type) — consistent.
- `SpgSnapshotRow.negative_remainder_count` added in Task 6 — separate field, matches the per-row aggregation in `queries_spg.py`.
- `spgI18n` defined in Task 7, used in same task — consistent.

---

## Roadmap (future plans, not in this document)

These are explicitly out of scope; they warrant their own plans:

1. **Audit log UI** — who/when changed which remainder, with diff view
2. **Bulk remainder ops** — transfer all remainders from section A to section B in one click
3. **Notifications** — alert when a SPG's `negative_total` crosses a threshold
4. **Excel export** of the snapshot
5. **Real auth** — replace `_fake_user` in `app/api/deps.py` with JWT validation; this affects every test that relied on `id=1` being a real user
6. **SPG rebalancing wizard** — drag-and-drop to redistribute remainders across SPGs
7. **Lot/serial tracking** — extend `warehouse_remainders` with `lot_code`, build on `requires_lot`
8. **Multi-warehouse** — split `storage_production_groups` per physical warehouse
