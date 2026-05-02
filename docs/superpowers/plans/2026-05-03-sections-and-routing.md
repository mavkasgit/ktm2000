# Sections & Routing Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `Section` model with `sort_order`, add full CRUD API including `GET /api/sections/{id}`, seed default factory sections via migration, and document routing business rules for anodized aluminum profile production.

**Architecture:** The `Section` model remains a simple reference catalog (no `is_required` flag — route step presence/absence determines participation per-article). Add `sort_order: int` to support UI ordering and route sequence inference. Seed 7 default sections (WH, DRILL, PRESS, SHOT, ANOD, SAW, PACK) via Alembic migration. Document MVP routing assumptions and future per-article route flexibility.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, Alembic, pytest.

---

## File Structure

- `backend/app/models/section.py` — Add `sort_order: Mapped[int]` column (non-nullable, default=0).
- `backend/app/api/routes/sections.py` — Add `GET /{section_id}`, include `sort_order` in schemas.
- `backend/alembic/versions/0007_add_section_sort_order.py` — Migration: add column + backfill existing rows with `id` as order.
- `backend/alembic/versions/0008_seed_factory_sections.py` — Migration: insert 7 default sections.
- `backend/tests/test_master_data.py` — Update tests for `sort_order` and `GET by id`.
- `docs/superpowers/plans/routing-rules.md` — Document MVP routing assumptions and future per-article flexibility.

---

### Task 1: Add `sort_order` to Section Model

**Files:**
- Modify: `backend/app/models/section.py`

- [ ] **Step 1: Add `sort_order` column**

```python
# After existing columns, before created_at
sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
```

Import `Integer` from `sqlalchemy` at top.

---

### Task 2: Update Sections API

**Files:**
- Modify: `backend/app/api/routes/sections.py`

- [ ] **Step 1: Add `sort_order` to schemas**

Update `SectionIn`, `SectionOut`, `SectionPatch` to include `sort_order: int` (optional for Patch).

- [ ] **Step 2: Add `GET /{section_id}` endpoint**

```python
@router.get("/{section_id}", response_model=SectionOut)
async def get_section(section_id: int, db: AsyncSession = Depends(get_db)) -> SectionOut:
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return SectionOut.model_validate(item, from_attributes=True)
```

- [ ] **Step 3: Update `list_sections` to order by `sort_order`**

```python
items = (await db.execute(select(Section).order_by(Section.sort_order, Section.id))).scalars().all()
```

---

### Task 3: Create Migration — Add `sort_order` Column

**Files:**
- Create: `backend/alembic/versions/0007_add_section_sort_order.py`

- [ ] **Step 1: Generate migration via Alembic**

```bash
cd backend && alembic revision --autogenerate -m "add section sort_order"
```

- [ ] **Step 2: Review and adjust migration**

Ensure:
- `op.add_column` adds `sort_order` with `server_default='0'`
- `op.execute("UPDATE sections SET sort_order = id")` backfills existing rows
- `op.alter_column` drops server_default if desired

- [ ] **Step 3: Apply migration locally**

```bash
cd backend && alembic upgrade head
```

---

### Task 4: Create Migration — Seed Factory Sections

**Files:**
- Create: `backend/alembic/versions/0008_seed_factory_sections.py`

- [ ] **Step 1: Write migration**

```python
"""seed factory sections

Revision ID: 0008_seed_factory_sections
Revises: 0007_add_section_sort_order
Create Date: 2026-05-03 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008_seed_factory_sections"
down_revision: Union[str, None] = "0007_add_section_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SECTIONS = [
    {"code": "WH", "name": "Склад", "sort_order": 10, "description": "Выдача сырья и приём готовой продукции"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "description": "Сверловка отверстий"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "description": "Прессование профилей"},
    {"code": "SHOT", "name": "Дробеструйная обработка", "sort_order": 40, "description": "Подготовка поверхности перед анодированием"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "description": "Анодирование алюминиевого профиля"},
    {"code": "SAW", "name": "Пила", "sort_order": 60, "description": "Резка профиля на заданную длину"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 70, "description": "Упаковка готовой продукции"},
]

def upgrade() -> None:
    for section in SECTIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO sections (code, name, sort_order, description, is_active, created_at)
                VALUES (:code, :name, :sort_order, :description, true, NOW())
                ON CONFLICT (code) DO NOTHING;
                """
            ).bindparams(**section)
        )

def downgrade() -> None:
    codes = [s["code"] for s in SECTIONS]
    op.execute(
        sa.text("DELETE FROM sections WHERE code = ANY(:codes)").bindparams(codes=codes)
    )
```

- [ ] **Step 2: Apply migration**

```bash
cd backend && alembic upgrade head
```

---

### Task 5: Update Tests

**Files:**
- Modify: `backend/tests/test_master_data.py`

- [ ] **Step 1: Add test for `sort_order` in create**

```python
async def test_create_section_with_sort_order(client) -> None:
    payload = {"code": "TEST", "name": "Test Section", "sort_order": 99}
    resp = await client.post("/api/sections", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["sort_order"] == 99
```

- [ ] **Step 2: Add test for `GET /api/sections/{id}`**

```python
async def test_get_section_by_id(client) -> None:
    # Create first
    create_resp = await client.post("/api/sections", json={"code": "GETME", "name": "Get Me", "sort_order": 5})
    section_id = create_resp.json()["id"]
    
    resp = await client.get(f"/api/sections/{section_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "GETME"
    assert data["sort_order"] == 5
```

- [ ] **Step 3: Add test for 404 on missing section**

```python
async def test_get_section_not_found(client) -> None:
    resp = await client.get("/api/sections/99999")
    assert resp.status_code == 404
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_master_data.py -v
```

---

### Task 6: Document Routing Rules

**Files:**
- Create: `docs/superpowers/plans/routing-rules.md`

- [ ] **Step 1: Write routing rules document**

```markdown
# Routing Rules for Anodized Aluminum Profile Production

## Default MVP Route

WH → [DRILL | PRESS | ничего] → SHOT → ANOD → SAW → PACK

### Step-by-Step

1. **WH** (Склад) — Always first. Material issuance.
2. **DRILL** or **PRESS** — Alternative first production steps. Some articles skip both.
3. **SHOT** — Currently treated as default required, but future per-article routes may skip it.
4. **ANOD** — Always required. Anodization.
5. **SAW** — Always required. Cutting to length.
6. **PACK** — Always required. Packaging.

## Important Design Decisions

- **Do NOT hard-code SHOT as globally mandatory.**
  - Current behavior: SHOT is included by default.
  - Future behavior: per-article route configuration can omit SHOT.
  
- **DRILL and PRESS are alternatives, not sequential.**
  - An article uses either DRILL or PRESS as the first production step, or skips both.
  
- **Skipped operations = absence of route step, not a fake "SKIP" section.**
  - Never create a "SKIP" or "NONE" section in the database.
  
- **Section.obligatory does not exist.**
  - Obligatoriness is a property of the article-route-step relationship, not the section itself.
  - Future model: `article_route_steps(article_id, step_order, section_code, is_optional)`.

## Operations from Plan → Route Steps Mapping

| Excel Operation | Route Step |
|----------------|------------|
| окно | PRESS → ANOD → SAW → PACK |
| гребенка | PRESS → DRILL → ANOD → SAW → PACK |
| сверло | PRESS → DRILL → ANOD → SAW → PACK |
| клей | PRESS → ANOD → SAW → PACK |
| рассеиватель | PRESS → ANOD → SAW → PACK |

Note: For MVP, SHOT is inserted before ANOD for all routes.
```

---

## Verification Checklist

- [ ] `GET /api/sections` returns sections ordered by `sort_order`
- [ ] `GET /api/sections/1` returns single section
- [ ] `POST /api/sections` accepts `sort_order`
- [ ] `PATCH /api/sections/{id}` can update `sort_order`
- [ ] Migration `0007` adds column and backfills
- [ ] Migration `0008` seeds 7 default sections
- [ ] All tests pass
- [ ] Routing rules documented

---

## Notes for Future Work

- When per-article routes are implemented, create `article_route_steps` table with `is_optional` flag.
- SHOT skipping will be controlled at the article-route level, not section level.
- Consider adding `Section.is_production` flag if non-production sections (e.g., QC labs) are added later.
