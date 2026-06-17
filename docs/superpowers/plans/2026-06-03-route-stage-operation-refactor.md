# RouteStage + RouteOperation Refactor

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Status (2026-06-03):** Phases 1, 2, 4 complete. Phase 3 deferred.

**Goal:** Replace the `RouteStep.combined_op_group` string-tag merge trick with a clean data model where each section-bound task (`RouteStage`) holds an explicit list of operations (`RouteOperation`).

**Architecture:**
- New tables `route_stages` (one row per task on a section) and `route_operations` (N rows per stage).
- `RouteStep` and `combined_op_group` are dropped in the final phase.
- `SectionPlanLine.route_step_id` becomes `route_stage_id`.
- Backwards-compatible: old routes keep working via dual-read.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, FastAPI, pytest.

---

## Files Touched (rough count)

- Models: 5 (`route.py`, `internal_plan.py`, `work_task.py`, `warehouse_remainder.py`, `__init__.py`)
- Services: 6 (`plan_generation.py`, `plan_import_service.py`, `production_planning_rows.py`, `route_builder.py`, `route_selection.py`, `shopfloor/queries_sections.py`, `shopfloor/queries_details.py`, `shopfloor/operations_tasks.py`, `shopfloor/common.py`, `transfers/queries.py`)
- API: 4 (`routes/routes.py`, `routes/route_rule_profiles.py`, `routes/production_planning.py`, `routes/production_plans.py`, `routes/spg.py`)
- Seeders: 1 (`seeds/seeders/routes_seeder.py`)
- Tests: ~10 files

`grep RouteStep|route_steps` returns **363 matches** today.

---

## Phase 1 — New model + migration, no behavior change (small)

**Goal:** Add `RouteStage` / `RouteOperation` tables. Backfill from existing `RouteStep` rows. Existing code keeps using `RouteStep` — no call-sites change.

- [ ] **Task 1.1:** Add `RouteStage` and `RouteOperation` to `app/models/route.py`
- [ ] **Task 1.2:** Add Alembic migration `013_route_stages_and_operations.py`
  - Create `route_stages` (id, route_id, sequence, section_id, is_significant, norm_time_minutes, requires_acceptance, allow_parallel, is_final, sort_order)
  - Create `route_operations` (id, route_stage_id, sequence, operation_code, operation_name)
  - Backfill: for each `RouteStep`, find or create a matching `RouteStage` keyed by (route_id, section_id). Group existing steps that share (route_id, section_id, combined_op_group) into one stage; standalone steps become their own stage.
  - Sequence: use the smallest `sequence` of the group; for the `is_final` flag, take the OR over the group.
  - Each `RouteStep` operation becomes a `RouteOperation` in the corresponding stage.
- [ ] **Task 1.3:** Add a `RouteStep.route_stage_id` nullable FK on the old table, pointing to the new stage (for back-tracing).
- [ ] **Task 1.4:** Add `SectionPlanLine.route_stage_id` nullable FK (forward-link for the next phase).
- [ ] **Task 1.5:** Smoke-test the migration on a fresh DB + on a backfilled DB. Verify row counts match.
- [ ] **Task 1.6:** Commit.

**Acceptance:** Migration applies cleanly forward and back. After migration, `SELECT COUNT(*) FROM route_stages` is reasonable (no steps lost).

---

## Phase 2 — Switch `plan_generation` to `RouteStage` (medium)

**Goal:** Plan generation reads from `RouteStage` and writes `SectionPlanLine.route_stage_id`. The old `RouteStep` path stays for legacy read-only consumers (API queries).

- [ ] **Task 2.1:** Refactor `app/services/plan_generation.py:_get_route_steps_with_sections` to return `[(RouteStage, Section, list[RouteOperation])]`.
- [ ] **Task 2.2:** Update `SectionPlanLine` creation in plan gen to set `route_stage_id`.
- [ ] **Task 2.3:** When plan gen reads `RouteStage`, also write `route_step_id` for back-compat (copy the corresponding old step if it exists).
- [ ] **Task 2.4:** Add tests in `tests/test_plan_generation_route_stage.py` (group-by-section produces one line, multiple operations stored as JSON, is_final set correctly).
- [ ] **Task 2.5:** Run full test suite. Fix any references to `RouteStep.operation_code` that now need to read from `RouteStage.operations[].operation_code`.
- [ ] **Task 2.6:** Commit.

**Acceptance:** All existing plan-generation tests pass with new model. `SectionPlanLine` rows have `route_stage_id` set.

---

## Phase 3 — API for new model (medium)

**Goal:** CRUD endpoints for `RouteStage` and `RouteOperation`. Old `RouteStep` API marked `@deprecated`.

- [ ] **Task 3.1:** Add Pydantic schemas: `RouteStageCreate`, `RouteStageUpdate`, `RouteOperationCreate`.
- [ ] **Task 3.2:** Add API endpoints:
  - `POST /api/routes/{route_id}/stages` — create stage (auto-generates RouteOperations)
  - `PATCH /api/routes/{route_id}/stages/{stage_id}` — update stage + operations
  - `DELETE /api/routes/{route_id}/stages/{stage_id}` — remove stage
- [ ] **Task 3.3:** On stage create/update, auto-create a matching `RouteStep` row (dual-write) for back-compat.
- [ ] **Task 3.4:** Mark old `POST /api/routes/{route_id}/steps` as deprecated; it still works but logs a warning.
- [ ] **Task 3.5:** Update `app/services/route_builder.py` to use the new API when constructing routes.
- [ ] **Task 3.6:** Add tests for new endpoints.
- [ ] **Task 3.7:** Commit.

**Acceptance:** New API works. Old API still works. Tests green.

---

## Phase 4 — Drop `RouteStep` (large)

**Goal:** Remove the old `RouteStep` table and `combined_op_group` field. All 363 references migrated to `RouteStage`.

- [ ] **Task 4.1:** Replace `RouteStep` reads with `RouteStage` reads across the codebase. Touch files in this order (highest-dependency first):
  - `app/services/plan_generation.py` (already done in Phase 2)
  - `app/services/plan_import_service.py`
  - `app/services/production_planning_rows.py`
  - `app/services/route_selection.py`
  - `app/services/route_builder.py`
  - `app/services/shopfloor/queries_sections.py`
  - `app/services/shopfloor/queries_details.py`
  - `app/services/shopfloor/operations_tasks.py`
  - `app/services/shopfloor/common.py`
  - `app/transfers/queries.py`
  - `app/api/routes/production_planning.py`
  - `app/api/routes/production_plans.py`
  - `app/api/routes/spg.py`
  - `app/api/routes/routes.py`
  - `app/api/routes/route_rule_profiles.py`
  - `app/seeds/seeders/routes_seeder.py`
- [ ] **Task 4.2:** Update `SectionPlanLine` to use `route_stage_id` only (drop `route_step_id`).
- [ ] **Task 4.3:** Update `WorkTask.route_step_id` → `route_stage_id`.
- [ ] **Task 4.4:** Update `WarehouseRemainder.route_step_id` → `route_stage_id`.
- [ ] **Task 4.5:** Migration `014_drop_route_steps.py`:
  - Drop `route_steps` table
  - Drop `route_step_id` columns from `section_plan_lines`, `work_tasks`, `warehouse_remainders`
  - Make `route_stage_id` columns NOT NULL
- [ ] **Task 4.6:** Update tests in `tests/test_routes_seed.py`, `tests/test_route_steps_preview.py`, `tests/test_combined_operations.py`, `tests/test_spg_route_lifecycle.py`, `tests/test_transfers_module.py`, `tests/test_production_planning_rows.py` — replace `RouteStep` fixtures with `RouteStage` + `RouteOperation`.
- [ ] **Task 4.7:** Update conftest fixtures (`tests/conftest.py`) to expose `route_stage_factory` helper.
- [ ] **Task 4.8:** Run full test suite. Fix anything red.
- [ ] **Task 4.9:** Update `app/models/route.py` — remove `RouteStep` class.
- [ ] **Task 4.10:** Delete `alembic/versions/011_combined_op_group.py` references in any docs.
- [ ] **Task 4.11:** Final commit.

**Acceptance:** No `RouteStep` references anywhere. `combined_op_group` field gone. Full test suite green.

---

## Risks

1. **Production data:** Migration backfill must preserve all existing route structure. Verify with `SELECT COUNT(*)` checks before/after.
2. **SectionPlanLine.route_step_id → route_stage_id:** Lots of FK references; coordinate the migration with the model changes to avoid downtime.
3. **Tests:** 30+ test files use `RouteStep`. Phase 4 will have a long test-fix loop.

## Out of Scope (future work)

- Dropping `combined_op_group` from `RouteStep` (Phase 4 already does this when the table goes).
- UI changes for editing stages vs steps (separate ticket).
