# Syncgate switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отключить обязательную проверку HRMS/KTM во всех автоматических lifecycle-гейтах, сохранив ручной запуск и временную инфраструктуру.

**Architecture:** `scripts/verify-sync.mjs` получает флаг `--if-enabled`: без `KTM_SYNCGATE` он завершается успешно с сообщением о пропуске, с `1|true|yes|on` выполняет прежнее сравнение, с другим значением завершается с кодом 2. Корневой и frontend lifecycle вызывают гейт с `--if-enabled`; ручной `npm run verify:sync` остаётся без этого флага.

**Tech Stack:** Node.js ESM, npm lifecycle scripts, Vitest.

**Spec:** Согласованный в диалоге дизайн от 2026-09-25; ADR-0029.

## Global Constraints

- `../hrms` не удаляется.
- `npm run verify:sync` остаётся принудительной проверкой независимо от `KTM_SYNCGATE`.
- Не изменять чужие WIP: `backend/tests/stock/test_task_completion_transform.py`, `frontend/e2e/sawing-four-lengths-cycle.spec.ts`.
- Не добавлять зависимости.

---

### Task 1: Переключатель CLI

**Files:**
- Modify: `scripts/verify-sync.mjs`
- Test: `frontend/scripts/verify-sync.test.mjs`

**Interfaces:**
- Consumes: `KTM_SYNCGATE`, argv-флаг `--if-enabled`.
- Produces: `parseArgs(...) -> { other, root, ifEnabled }`; CLI exit 0 при пропуске, 2 при неверном значении, прежние 0/1 при реальной проверке.

- [ ] Добавить тесты CLI: без переменной с `--if-enabled` — exit 0 и сообщение о пропуске; `TRUE` — реальная проверка; `maybe` — exit 2 и сообщение с допустимыми значениями; без `--if-enabled` переменная не влияет.
- [ ] Запустить целевой Vitest и убедиться, что новые тесты падают.
- [ ] Добавить разбор `--if-enabled` и проверку env в `main()`; ручной путь оставить безусловным.
- [ ] Повторно запустить целевой Vitest.

### Task 2: Lifecycle-подключение

**Files:**
- Modify: `package.json`
- Modify: `frontend/package.json`
- Test: `frontend/scripts/verify-sync.integration.test.mjs`

**Interfaces:**
- Consumes: CLI `--if-enabled`.
- Produces: `predev`, корневой `prebuild` и frontend `prebuild` без зависимости от HRMS по умолчанию.

- [ ] Добавить `--if-enabled` в `package.json:8-9` и `frontend/package.json:9`.
- [ ] Сделать реальный HRMS integration test условным: без `KTM_SYNCGATE` он пропускается, при поддержанном значении выполняется.
- [ ] Проверить `npm run verify:sync` с существующим `../hrms`.
- [ ] Проверить frontend build без обращения к HRMS.

### Task 3: Документация решения

**Files:**
- Create: `docs/adr/0029-vremennaya-priostanovka-syncgate-hrms-ktm.md`
- Modify: `docs/adr/0007-shared-auth-shell-unified-style.md`
- Modify: `docs/adr/0011-auth-backend-host-adapter-sync.md`
- Modify: `CONTEXT.md:357-362`
- Modify: `README.md:53-66`

**Interfaces:**
- Consumes: согласованное временное приостановление.
- Produces: актуальный глоссарий и инструкция по `KTM_SYNCGATE`.

- [ ] Добавить ADR-0029 с решением, альтернативами и последствиями.
- [ ] Отметить ADR-0007/0011 как принятые, но с приостановленным обязательным enforcement со ссылкой на ADR-0029.
- [ ] Убрать из `CONTEXT.md` утверждение об обязательной байтовой синхронизации.
- [ ] Добавить в README команды включения Syncgate и принудительной ручной проверки.

### Task 4: Проверка

**Files:**
- No source changes expected.

- [ ] Запустить `npm --prefix frontend exec vitest run scripts/verify-sync.test.mjs scripts/verify-sync.integration.test.mjs`.
- [ ] Запустить `npm run verify:sync` и проверить exit 0.
- [ ] Запустить `npm --prefix frontend run build` и проверить успешный build без lifecycle-гейта.
- [ ] Запустить фактический `npm run dev` на коротком интервале, подтвердить запуск DB/backend/frontend и отсутствие обращения к `../hrms`, затем остановить только запущенные процессы.
- [ ] Выполнить `npx @colbymchenry/codegraph sync`.
