# Дневные планы участка — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить frontend-прототип дневных планов на сохранённые серверные планы участка с фильтрацией, созданием, отзывом, историей и печатью.

**Architecture:** `DailyPlan` хранит участок, дату, автора и время создания; `DailyPlanItem` хранит только связь с `WorkTask`. Создание и отзыв проходят через отдельный backend-модуль с `AsyncSession`, а состав всегда читается как актуальная проекция `WorkTask`. Frontend получает сводку планов и состав выбранных планов через отдельные запросы, а существующий `PlanModal` печатает фактически отображаемый набор.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, PostgreSQL, React 18.3, TypeScript, TanStack Query, Vitest, Playwright.

**Spec:** Согласованная модель: `DailyPlan` — набор актуальных заданий участка на фиксированную дату; дата неизменна; одинаковая дата допустима у нескольких планов; один `WorkTask` активен максимум в одном плане; отзыв удаляет только связь и пишет audit; выполнение меняется только на странице участка.

## Global Constraints

- Backend использует только `AsyncSession`.
- Не хранить snapshot полей `WorkTask` в дневном плане.
- Не добавлять уникальность `(section_id, plan_date)`.
- `created_at` назначает сервер; дата фиксируется при создании и не редактируется.
- Создание принимает только актуальные незавершённые задания своего участка.
- Одно задание не может принадлежать двум активным планам; БД — единственный backstop.
- Отзыв не удаляет и не отменяет `WorkTask`, только membership плана; audit остаётся.
- В режиме `План` нет completion actions; печатается текущий отображаемый набор.
- Чужой WIP не менять, не откатывать и не включать в изменения.

## File Map

- Create: `backend/app/models/daily_plan.py` — ORM-модели и ограничения.
- Modify: `backend/app/models/__init__.py` — metadata registration.
- Create: `backend/alembic/versions/061_daily_plans.py` — таблицы, FK, unique, indexes.
- Create: `backend/app/services/daily_plan_service.py` — live queries, create, revoke, audit.
- Create: `backend/app/api/routes/daily_plans.py` — HTTP adapter и role dependencies.
- Modify: `backend/app/main.py` — register router.
- Create: `backend/tests/test_daily_plans_api.py` — HTTP behavior tests through auth + AsyncSession.
- Modify: `backend/tests/test_migrations.py` — migration/head metadata assertions if existing pattern requires it.
- Modify: `frontend/src/shared/api/shopfloor.ts` — DTO and HTTP adapters.
- Modify: `frontend/src/shared/api/queryKeys.ts` — query key hierarchy.
- Create: `frontend/src/features/sections/components/DailyPlanCreateDialog.tsx` — date and task selection; no completion action.
- Create: `frontend/src/features/sections/lib/dailyPlans.ts` — pure merge/progress/candidate helpers.
- Modify: `frontend/src/features/sections/components/DailyPlansPanel.tsx` — real summaries, selection, create/revoke callbacks.
- Modify: `frontend/src/features/sections/pages/SectionsTasksPage.tsx` — queries, mutations, composition merge, read-only plan mode, printing.
- Delete: `frontend/src/features/sections/lib/dailyPlanPrototype.ts` — obsolete fixture.
- Modify: `CONTEXT.md` — glossary terms only.
- Create: `docs/adr/0027-daily-plans-as-live-task-groupings.md` — only if the decision remains a real hard-to-reverse boundary.

## Public Interfaces

```text
GET  /api/daily-plans/sections/{sectionId}
POST /api/daily-plans
GET  /api/daily-plans/{planId}/items
POST /api/daily-plans/{planId}/items/{workTaskId}/revoke
```

Request:

```json
{"plan_date":"2026-09-24","work_task_ids":[101,102]}
```

DailyPlan response fields: `id`, `section_id`, `plan_date`, `created_at`, `created_by`, read-only `item_count`, `progress_percent`.

## Tasks

### Task 1: ORM and migration

- [ ] Add `DailyPlan` and `DailyPlanItem` models.
- [ ] Add composite PK `(daily_plan_id, work_task_id)` and global unique `work_task_id`.
- [ ] Add indexes for section/date list and plan membership.
- [ ] Register models and create migration from head `060_length_model_cutover` as `061_daily_plans`.
- [ ] Run migration metadata checks.

### Task 2: Backend module and HTTP seam

- [ ] Implement list summaries without copying tasks; include live completed WorkTasks in composition.
- [ ] Implement atomic create with same-section, non-terminal, unique-membership validation.
- [ ] Implement revoke deleting only item and writing audit in same transaction.
- [ ] Register router under `/api`; use `READER_ROLES` for reads and `WRITER_ROLES` for mutations.
- [ ] Add focused HTTP tests through public endpoints, including same-date plans, duplicate membership rejection, completed-task retention, revoke audit and no WorkTask mutation.

### Task 3: Frontend real data and create/revoke flow

- [ ] Add DTOs, HTTP functions, query keys and API-backed list/composition queries.
- [ ] Replace fixture helpers with pure live composition merge and candidate filters.
- [ ] Add create dialog for date and current active tasks.
- [ ] Add revoke action in plan composition, independent from completion.
- [ ] Preserve selected empty-plan semantics; never fall back to all tasks when a plan is selected.
- [ ] Remove prototype module, prototype toast, and dead buttons.

### Task 4: Verification and documentation

- [ ] Pass `PlanModal` the current displayed tasks so print output follows selected plans.
- [ ] Update `CONTEXT.md` with `DailyPlan` and `DailyPlanItem` terms; do not add implementation details.
- [ ] Add ADR only if the hard-to-reverse/surprising/tradeoff criteria remain true.
- [ ] Run focused backend tests via launcher, frontend build/unit tests, and authenticated UI smoke.

## Verification

Backend:

```powershell
npm run test:pytest -- backend/tests/test_daily_plans_api.py
npm run test:pytest -- backend/tests/test_migrations.py
```

Frontend:

```powershell
npm --prefix frontend run build
npm --prefix frontend run test -- src/features/sections
```

UI: use the existing authenticated Playwright surface; verify tabs, list/select, create, revoke, empty selected plan, read-only plan mode, print set, and no completion action from Plan.

## Self-review

- Snapshot avoidance: no `DailyPlan` task fields; only `work_task_id` membership.
- Same-date plans: no date uniqueness constraint.
- One active membership: global unique `work_task_id`; revoke deletes membership and permits re-add.
- Completed rows: composition joins live WorkTask and does not filter terminal status.
- Creation and revoke: separate endpoints/actions, not completion.
- Printing: one `printableTasks` source used by `PlanModal`.
- Existing WIP: only files in this task's map are changed; no resets, stashes, or broad commits.
