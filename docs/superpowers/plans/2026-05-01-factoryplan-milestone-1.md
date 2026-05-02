# FactoryPlan Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Milestone 1: create a production plan, fill it from an Excel import as the first source, and generate section tasks from product routes.

**Architecture:** The system follows the proven HRMS local-app structure: FastAPI async backend, PostgreSQL, React SPA frontend, dev/test/prod compose files under `infra/`, root npm orchestration scripts, and Playwright e2e. The backend owns all business invariants: import validation, route validation, plan release, movement ledger, and role checks. The frontend is a task-oriented UI over API resources, with no production math duplicated client-side except display formatting.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy asyncio, asyncpg, Alembic, PostgreSQL, structlog, python-jose, passlib/bcrypt, python-calamine, TypeScript, React, Vite, React Router, TanStack Query, axios, Tailwind, Radix/shadcn-style shared UI, lucide-react, Recharts, Vitest, Playwright, Docker Compose.

---

## Scope

This plan implements:

- HRMS-style dev/test/prod Docker Compose skeleton;
- backend service;
- frontend service;
- database schema;
- auth and roles;
- product, section, BOM and route CRUD;
- production plan and plan positions;
- Excel upload and validation as the first source of plan positions;
- plan position approval;
- release batches for selected planning horizons;
- generation of section plan lines and work tasks;
- cached task and route-step totals derived from movements.

This plan does not implement the full shopfloor movement ledger UI. It should still create the data model boundaries for immutable released positions, release batches, route snapshots, plan adjustments, defects, and cached totals so later milestones do not need a schema redesign.

## HRMS Reuse Rules

For shared infrastructure and application foundation, do not write from a blank slate. Inspect the working HRMS implementation first and create the FactoryPlan equivalent with the same structure where it fits.

Use HRMS as reference for:

- root scripts: `C:\Users\user\VibeCoding\hrms\package.json`;
- compose layout: `C:\Users\user\VibeCoding\hrms\infra\docker-compose.dev.yml`, `test`, `prod`;
- backend settings/database/logging: `backend/app/core/config.py`, `database.py`, `logging.py`;
- FastAPI app/router layout: `backend/app/main.py`, `backend/app/api/*`;
- Alembic layout: `backend/alembic/*`;
- Excel parsing mechanics: `backend/app/api/import_employees.py`;
- frontend axios client: `frontend/src/shared/api/axios.ts`;
- frontend router/layout/sidebar: `frontend/src/app/Router.tsx`, `Layout.tsx`, `shared/ui/sidebar.tsx`;
- shared UI primitives: `frontend/src/shared/ui/*`;
- TanStack Query entity pattern: `frontend/src/entities/*`;
- Playwright layout: `e2e/ui`, `e2e/api`, `e2e/domain`, `e2e/pages`, `e2e/fixtures`.

Do not copy HRMS domain logic. FactoryPlan domain services, tables, invariants, import diff, release batches, movements, transfers, defects, and plan adjustments are new domain work.

## File Structure

Create using HRMS as implementation reference, not from scratch:

- `package.json` - root orchestration scripts based on `C:\Users\user\VibeCoding\hrms\package.json`.
- `.env.dev`, `.env.test`, `.env.prod`, `.env.example` - based on HRMS env layout.
- `infra/docker-compose.dev.yml` - based on `C:\Users\user\VibeCoding\hrms\infra\docker-compose.dev.yml`.
- `infra/docker-compose.test.yml` - based on HRMS test compose.
- `infra/docker-compose.prod.yml` - based on HRMS prod compose.
- `backend/requirements.txt` - backend dependencies, based on `C:\Users\user\VibeCoding\hrms\backend\requirements.txt`.
- `backend/app/main.py` - FastAPI app entrypoint.
- `backend/app/core/config.py` - environment settings.
- `backend/app/core/security.py` - password hashing and auth helpers.
- `backend/app/core/database.py` - SQLAlchemy async engine/session, based on HRMS.
- `backend/app/models/base.py` - declarative base.
- `backend/app/models/*.py` - database models.
- `backend/app/schemas/*.py` - Pydantic request/response DTOs.
- `backend/app/api/*.py` - API route modules, matching HRMS module layout.
- `backend/app/services/excel_import.py` - Excel parsing and normalization.
- `backend/app/services/plan_validation.py` - validation of plan positions.
- `backend/app/services/plan_generation.py` - generation of section tasks.
- `backend/app/services/release_batches.py` - selected horizon release and route snapshot creation.
- `backend/app/services/totals_cache.py` - derived quantity cache recalculation.
- `backend/alembic/*` - migrations.
- `backend/tests/*` - unit and integration tests.
- `frontend/package.json` - frontend dependencies.
- `frontend/src/app/main.tsx` - React entrypoint, based on HRMS.
- `frontend/src/app/Router.tsx` - route definitions, based on HRMS.
- `frontend/src/shared/api/axios.ts` - axios client, based on HRMS.
- `frontend/src/shared/ui/*` - shared UI components copied/adapted from HRMS.
- `frontend/src/entities/*` - typed API modules and TanStack Query hooks.
- `frontend/src/features/*` - domain workflows.
- `frontend/src/pages/*` - page components.

## Task 1: HRMS-Style Project Skeleton

**Files:**

- Create: `package.json`
- Create: `.env.dev`
- Create: `.env.test`
- Create: `.env.prod`
- Create: `.env.example`
- Create: `infra/docker-compose.dev.yml`
- Create: `infra/docker-compose.test.yml`
- Create: `infra/docker-compose.prod.yml`
- Create: `backend/requirements.txt`
- Create: `backend/app/main.py`
- Create: `frontend/package.json`
- Create: `frontend/src/app/main.tsx`

- [ ] **Step 1: Mirror HRMS infrastructure layout**

Use these HRMS files as direct references:

- `C:\Users\user\VibeCoding\hrms\package.json`
- `C:\Users\user\VibeCoding\hrms\infra\docker-compose.dev.yml`
- `C:\Users\user\VibeCoding\hrms\infra\docker-compose.test.yml`
- `C:\Users\user\VibeCoding\hrms\infra\docker-compose.prod.yml`
- `C:\Users\user\VibeCoding\hrms\scripts\wait-for-container-health.ps1`

Create the same structure for FactoryPlan with renamed containers/databases:

- `factoryplan-postgres`;
- `factoryplan_dev`;
- `factoryplan_test`;
- `factoryplan_prod`.

Do not add Redis/worker in MVP unless a task explicitly needs background execution.

- [ ] **Step 2: Create backend requirements from HRMS baseline**

Start from `C:\Users\user\VibeCoding\hrms\backend\requirements.txt`.

Keep:

- FastAPI;
- uvicorn;
- sqlalchemy[asyncio];
- asyncpg;
- alembic;
- pydantic;
- pydantic-settings;
- structlog;
- python-jose;
- passlib[bcrypt];
- python-multipart;
- httpx;
- python-dateutil;
- python-calamine;
- pytest;
- pytest-asyncio.

Do not carry HRMS-only document dependencies unless FactoryPlan needs them.

- [ ] **Step 3: Create frontend package from HRMS baseline**

Start from `C:\Users\user\VibeCoding\hrms\frontend\package.json`.

Keep:

- React;
- Vite;
- TypeScript;
- React Router;
- TanStack Query;
- axios;
- Tailwind;
- Radix primitives;
- class-variance-authority;
- lucide-react;
- date-fns;
- Recharts;
- Vitest.

- [ ] **Step 4: Add smoke endpoints**

Implement `GET /api/health` using HRMS `C:\Users\user\VibeCoding\hrms\backend\app\main.py` and `app/api/health.py` as references.

- [ ] **Step 5: Verify**

Run:

```bash
npm run dev
```

Expected:

- backend health endpoint returns 200;
- frontend opens without runtime errors;
- PostgreSQL container is healthy.

## Task 2: Database Base and Auth

**Files:**

- Create: `backend/app/core/config.py`
- Create: `backend/app/core/security.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/user.py`
- Create: `backend/app/models/section.py`
- Create: `backend/alembic/versions/0001_users_sections.py`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: Write auth tests**

Cover password hashing, login success, disabled user rejection, and role serialization.

- [ ] **Step 2: Implement models**

Use HRMS `backend/app/core/config.py`, `backend/app/core/database.py`, `backend/app/models/base.py`, and auth dependencies as references. Create `users` and `sections` tables with `bigint generated always as identity primary key`, timestamps, role enum, and optional `section_id` on users.

- [ ] **Step 3: Implement login**

Add `POST /api/auth/login` and `GET /api/auth/me`.

- [ ] **Step 4: Run tests**

Run:

```bash
pytest backend/tests/test_auth.py -v
```

Expected: all auth tests pass.

## Task 3: Products, BOM and Routes

**Files:**

- Create: `backend/app/models/product.py`
- Create: `backend/app/models/bom.py`
- Create: `backend/app/models/route.py`
- Create: `backend/app/api/routes/products.py`
- Create: `backend/app/api/routes/boms.py`
- Create: `backend/app/api/routes/routes.py`
- Create: `backend/alembic/versions/0002_products_boms_routes.py`
- Test: `backend/tests/test_master_data.py`

- [ ] **Step 1: Write master data tests**

Cover unique SKU, one active BOM per product, one active route per product, route step sequence uniqueness, and inactive section rejection.

- [ ] **Step 2: Implement models and migrations**

Create products, boms, bom_lines, production_routes, and route_steps.

- [ ] **Step 3: Implement CRUD APIs**

Add list, create, detail and patch endpoints for products, sections, BOMs and routes.

Use HRMS CRUD routing and entity patterns as references, especially:

- `C:\Users\user\VibeCoding\hrms\backend\app\api\departments.py`;
- `C:\Users\user\VibeCoding\hrms\backend\app\api\positions.py`;
- `C:\Users\user\VibeCoding\hrms\backend\app\repositories\employee_repository.py`.

Do not copy HRMS HR-domain fields. Copy only the API/repository/service structure where it fits.

- [ ] **Step 4: Run tests**

Run:

```bash
pytest backend/tests/test_master_data.py -v
```

Expected: all master data tests pass.

## Task 4: Excel Import

**Files:**

- Create: `backend/app/models/import_file.py`
- Create: `backend/app/models/production_plan.py`
- Create: `backend/app/services/excel_import.py`
- Create: `backend/app/services/plan_validation.py`
- Create: `backend/app/api/routes/imports.py`
- Create: `backend/alembic/versions/0003_imports_production_plans.py`
- Test: `backend/tests/test_excel_import.py`

- [ ] **Step 1: Write Excel parser tests**

Cover required columns, decimal quantity parsing, Russian date format, Excel serial date, empty SKU, unknown SKU, missing BOM, and missing route.

- [ ] **Step 2: Implement file storage**

Save original `.xlsx` to uploads volume and store SHA-256 in `import_files`.

- [ ] **Step 3: Implement parser**

Read `.xlsx` through `python-calamine`, apply column mapping, normalize rows, and create `plan_positions` linked to an `import_batch`.

Use HRMS `C:\Users\user\VibeCoding\hrms\backend\app\api\import_employees.py` as the reference for:

- `CalamineWorkbook.from_filelike(BytesIO(content))`;
- sheet list;
- sheet index selection;
- headers and rows preview;
- column mapping.

Do not copy HRMS confirm-import behavior. FactoryPlan must create `ImportBatch` and `PlanChangeSet` first, then apply only after user confirmation.

- [ ] **Step 4: Implement validation**

Attach blocking errors and warnings to each plan position.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest backend/tests/test_excel_import.py -v
```

Expected: parser and validation tests pass.

## Task 5: Production Plan Position Approval

**Files:**

- Modify: `backend/app/api/routes/imports.py`
- Create: `backend/app/api/routes/production_plans.py`
- Test: `backend/tests/test_production_plan_approval.py`

- [ ] **Step 1: Write approval tests**

Cover draft preview, validation status, approval blocked by errors, successful approval, and released position immutability.

- [ ] **Step 2: Implement preview endpoint**

Return counts by validation status and position-level errors.

- [ ] **Step 3: Implement approve endpoint**

Allow position approval only when there are no blocking errors.

- [ ] **Step 4: Run tests**

Run:

```bash
pytest backend/tests/test_production_plan_approval.py -v
```

Expected: approval tests pass.

## Task 6: Plan Generation

**Files:**

- Create: `backend/app/models/internal_plan.py`
- Create: `backend/app/models/work_task.py`
- Create: `backend/app/models/release_batch.py`
- Create: `backend/app/services/plan_generation.py`
- Create: `backend/app/services/release_batches.py`
- Modify: `backend/app/api/routes/production_plans.py`
- Create: `backend/alembic/versions/0004_internal_plans_tasks.py`
- Test: `backend/tests/test_plan_generation.py`

- [ ] **Step 1: Write generation tests**

Cover one product with three route steps, two products with different routes, no duplicate generation on retry, first task `ready`, later tasks `waiting_previous`, route snapshot at release time, and release quantity not exceeding approved position quantity.

- [ ] **Step 2: Implement internal plan models**

Create `release_batches`, `release_batch_positions`, `internal_plans`, `section_plan_lines`, and `work_tasks`.

- [ ] **Step 3: Implement generation service**

Generate one section plan line and one task for each approved release batch position route step in a single transaction.

- [ ] **Step 4: Implement API endpoint**

Add `POST /api/production-plans/{id}/release-batches` and `POST /api/release-batches/{id}/release`.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest backend/tests/test_plan_generation.py -v
```

Expected: generation tests pass.

Use HRMS `backend/tests/conftest.py` as the reference for async test database setup and factory fixtures. Adapt it to FactoryPlan models and keep `bigint identity` assumptions.

## Task 7: Frontend Shell and Master Data Screens

**Files:**

- Create: `frontend/src/app/Router.tsx`
- Create: `frontend/src/shared/api/axios.ts`
- Create: `frontend/src/shared/ui/*`
- Create: `frontend/src/features/products/*`
- Create: `frontend/src/features/sections/*`
- Create: `frontend/src/features/routes/*`

- [ ] **Step 1: Add HRMS-style API client**

Use `C:\Users\user\VibeCoding\hrms\frontend\src\shared\api\axios.ts` as the reference. Create axios client with `VITE_API_URL`, Authorization header, 401 handling, and normalized error logging.

- [ ] **Step 2: Add HRMS-style layout and shared UI**

Use these HRMS files as references:

- `frontend/src/app/Router.tsx`;
- `frontend/src/app/Layout.tsx`;
- `frontend/src/shared/ui/sidebar.tsx`;
- `frontend/src/shared/ui/button.tsx`;
- `frontend/src/shared/ui/table.tsx`;
- `frontend/src/shared/ui/dialog.tsx`;
- `frontend/src/shared/ui/input.tsx`;
- `frontend/src/shared/ui/select.tsx`;
- `frontend/src/shared/ui/badge.tsx`.

Create navigation for Imports, Production Plans, Release Batches, Products, Sections, Routes, Section Plan, Dashboard.

- [ ] **Step 3: Add master data screens**

Implement list/create/edit for products, sections and routes.

Follow HRMS frontend module style:

- `entities/<entity>/api.ts`;
- `entities/<entity>/types.ts`;
- `entities/<entity>/use<Entity>.ts`;
- pages under `src/pages`;
- workflow components under `src/features`.

- [ ] **Step 4: Verify in browser**

Run frontend and backend, create one product, one section, one BOM and one route.

## Task 8: Import and Plan Generation Screens

**Files:**

- Create: `frontend/src/features/imports/*`
- Create: `frontend/src/features/production-plans/*`
- Create: `frontend/src/features/section-plan/*`

- [ ] **Step 1: Build upload screen**

Support file selection, upload progress, mapping result and validation preview.

- [ ] **Step 2: Build production plan detail**

Show rows, validation errors, approval action, release batch creation and release action.

- [ ] **Step 3: Build section plan screen**

Show generated tasks grouped by section with status, planned quantity and due date.

- [ ] **Step 4: Run smoke flow**

Create master data, create a production plan, upload a sample Excel file into it, approve positions, create a release batch for selected positions, release it to production, and verify section tasks appear.

## Task 9: Documentation and Runbook

**Files:**

- Create: `README.md`
- Create: `docs/runbooks/local-development.md`
- Create: `docs/runbooks/restore.md`
- Create: `docs/examples/production-plan-import-template.xlsx`
- Create: `playwright.config.ts`
- Create: `e2e/ui/import-release-flow.spec.ts`
- Create: `e2e/pages/*`

- [ ] **Step 1: Document local setup**

Include prerequisites, environment variables, and `npm run dev` / `npm run db:up` commands matching the HRMS root-script style.

- [ ] **Step 2: Document Excel template**

Describe required and optional columns.

- [ ] **Step 3: Document restore**

Describe restoring PostgreSQL dump and uploads volume.

- [ ] **Step 4: Add HRMS-style Playwright structure**

Use these HRMS files as references:

- `C:\Users\user\VibeCoding\hrms\playwright.config.ts`;
- `C:\Users\user\VibeCoding\hrms\e2e\ui\structure-full-lifecycle.spec.ts`;
- `C:\Users\user\VibeCoding\hrms\e2e\pages\*.ts`;
- `C:\Users\user\VibeCoding\hrms\e2e\fixtures\*.ts`.

Create the FactoryPlan e2e layout with page objects and fixtures. The first flow should cover `create production plan -> import Excel -> apply diff -> approve positions -> create release batch -> release -> see section tasks`.

- [ ] **Step 5: Final verification**

Run backend tests, frontend build, and full manual smoke scenario.
