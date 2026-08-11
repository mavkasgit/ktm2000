# E2E Handoff — KTM-2000 Playwright

Документ для передачи задачи исполнителю/агенту. Канон запуска → [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md).

**Дата последнего прогона:** 2026-08-11  
**Результат:** `full-cycle.spec.ts` (@ui) — **passed** (~53s); `final-release.spec.ts` (#96, @smoke) — **passed**; backend transfer-тесты — 44 passed; `bulk-workflow.spec.ts` — skipped (сырой, устарел под текущий UI).

---

## Цель

Привести E2E-набор в рабочее состояние: минимум **5+ passed** из 8, 0 failed. Инфраструктура (Playwright + dev-окружение) **работает** — чинить нужно хелперы и тестовые данные.

---

## Контекст

| Что | Где |
|-----|-----|
| Спеки | `frontend/e2e/*.spec.ts` (4 файла, 8 тестов) |
| Фикстуры | `frontend/e2e/fixtures.ts` |
| Конфиг | `frontend/playwright.config.ts` |
| Тестовый Excel | `test.xls` (корень репо) |
| Документация | `frontend/e2e/AGENTS.md` |

Playwright **не поднимает** серверы сам (`webServer` закомментирован в config). Перед прогоном:

```bash
npm run dev   # из корня: Postgres + backend :8012 + frontend :5172
```

Запуск (Windows cmd):

```cmd
set E2E_API_URL=http://localhost:8012/api
set PLAYWRIGHT_TEST_BASE_URL=http://localhost:5172
cd frontend
npx playwright test
```

Один тест:

```cmd
npx playwright test e2e/route-workflow.spec.ts -g "import wizard"
```

---

## Результаты последнего прогона

| # | Файл | Тест | Статус | Причина |
|---|------|------|--------|---------|
| 1 | `bulk-workflow.spec.ts` | bulk operations shopfloor | **failed** | `products.find is not a function` |
| 2 | `route-workflow.spec.ts` | full workflow approve→take-to-work | **skipped** | 0 approvable positions после импорта |
| 3 | `route-workflow.spec.ts` | position route info in planning | **skipped** | нет валидного плана |
| 4 | `route-workflow.spec.ts` | execution page approved positions | **skipped** | нет approved |
| 5 | `route-workflow.spec.ts` | import wizard template options | **passed** | UI OK (2.6s) |
| 6 | `total-workflow.spec.ts` | seed + remainders SPG UI | **failed** | `products.find is not a function` |
| 7 | `total-workflow.spec.ts` | shortage strategies | **failed** | то же |
| 8 | `transfers-auto-accept.spec.ts` | send + issue ritual | **failed** | то же |

Артефакты падений: `frontend/test-results/` (screenshot, video, error-context.md).

---

## Корневая причина #1 — pagination API (4 failed)

`GET /api/products?q=…` возвращает **`ProductsListResponse`**, не массив:

```python
# backend/app/api/routes/products.py
class ProductsListResponse(BaseModel):
    items: List[ProductOut]
    total: int
```

Хелпер `apiGetProductBySku` в 3 спеках ожидает массив:

```typescript
const products = await res.json();
const product = products.find((p) => p.sku === sku);  // TypeError
```

**Затронутые файлы (дублированный хелпер в каждом):**

- `frontend/e2e/bulk-workflow.spec.ts` — строки ~22–33
- `frontend/e2e/total-workflow.spec.ts` — строки ~22–33
- `frontend/e2e/transfers-auto-accept.spec.ts` — строки ~41–52

**Уже правильный паттерн** в том же `bulk-workflow.spec.ts` для techcards:

```typescript
const body = await res.json();
const techcards = Array.isArray(body) ? body : body.items ?? [];
```

### Рекомендуемый фикс

1. Вынести общие API-хелперы в `frontend/e2e/api-helpers.ts`.
2. `unwrapItems<T>(body): T[]` — `Array.isArray(body) ? body : body.items ?? []`.
3. `apiGetProductBySku` — использовать `unwrapItems`, затем `.find`.
4. Прогнать 4 ранее падавших теста.

---

## Корневая причина #2 — несогласованный BACKEND_URL fallback

| Файл | Fallback если нет `E2E_API_URL` |
|------|----------------------------------|
| `bulk-workflow.spec.ts` | `http://localhost:8082` (prod nginx) |
| `route-workflow.spec.ts` | `http://localhost:8082` |
| `transfers-auto-accept.spec.ts` | `http://localhost:8082` |
| `total-workflow.spec.ts` | `http://localhost:8012` (dev) |

Для локальной разработки канон — **`:8012`** (актуальный dev-порт backend, см. `package.json` и vite-proxy). Рекомендация: единый fallback `http://localhost:8012` во всех спеках (или только через `api-helpers.ts`).

---

## Корневая причина #3 — skipped route-workflow (3 skipped)

Импорт `test.xls` через UI **работает** (диалог, preview 7 строк), но все позиции получают:

```
status=invalid, validation_status=invalid
Approvable positions: 0
```

Тесты корректно делают `test.skip()` — данных нет, не баг раннера.

**Варианты фикса (выбрать один):**

| Вариант | Действие |
|---------|----------|
| A | Обновить `test.xls` / seed так, чтобы позиции были `valid` |
| B | В `beforeAll` спеки — API-setup: seed routes + создать план с валидными позициями (как в `total-workflow`) |
| C | Использовать `npm run db:seed` + существующий план в БД вместо UI-импорта |

Перед skip-тестами логи показывают: upload complete, plan created, но validation fails.

---

## Фикстуры и auth

[`frontend/e2e/fixtures.ts`](../frontend/e2e/fixtures.ts):

- Логин: `admin@ktm2000.local` / `admin`
- Если URL не содержит `login` — считает, что auth bypass (dev `DEV_BYPASS_AUTH=true` в backend tests conftest; проверить dev `.env.dev`)
- `seedTestData` — POST `/api/routes/seed` (устаревший путь? в спеках используется `/api/routes-seed?force=true`)

Сверить актуальный seed endpoint в `backend/app/api/routes/`.

---

## Шаги для исполнителя

### PR-1: Починить pagination-хелперы (обязательно)

1. Создать `frontend/e2e/api-helpers.ts` с `BACKEND_URL`, `unwrapItems`, `apiGetProductBySku`, `apiSeedData`.
2. Заменить дубли в 3 спеках на импорт из helpers.
3. Унифицировать fallback URL → `:8012`.
4. Прогон: 4 ранее failed теста — должны пройти setup или упасть на следующем шаге (не на `.find`).

### PR-2: Починить route-workflow skips (желательно)

1. Разобрать, почему `test.xls` даёт `invalid` (логи API validation или `test_route_validation`).
2. Либо поправить данные, либо перейти на API-setup в `beforeAll`.
3. Прогон: 3 skipped → passed или явный skip с комментарием.

### PR-3: Документация

1. Обновить `frontend/e2e/AGENTS.md` — fallback `:8012`, ссылка на этот handoff.
2. После фикса — удалить или архивировать `docs/e2e-handoff.md` (или обновить статус).

---

## DoD (Definition of Done)

- [x] `npx playwright test` с `E2E_API_URL=http://localhost:8012/api`: `full-cycle.spec.ts` (@ui) passed
- [ ] Минимум 5 passed (допустимы skip только с явной причиной в комментарии)
- [ ] `apiGetProductBySku` не дублируется в 3 файлах — один `api-helpers.ts`
- [ ] Fallback `BACKEND_URL` единый во всех спеках
- [ ] `frontend/e2e/AGENTS.md` актуален

**Команда проверки:**

```cmd
set E2E_API_URL=http://localhost:8012/api
set PLAYWRIGHT_TEST_BASE_URL=http://localhost:5172
cd frontend && npx playwright test
```

---

## Границы (не делать)

- Не включать `webServer` в playwright.config без согласования (долгий старт, дублирует `npm run dev`).
- Не менять pagination API backend — тесты должны адаптироваться к `{ items, total }`.
- Не трогать unrelated backend/frontend код из git status (shopfloor, seeds и т.д.) — только `frontend/e2e/` и docs.

---

## Заметил, не тронул

- `apiGetOrCreateTechcard` в `transfers-auto-accept.spec.ts` уже обрабатывает `body.items` — образец для products.
- `route-workflow.spec.ts` использует `apiGetPlans` / `apiGetPositions` — проверить, не paginated ли они тоже.
- Root `package.json` имеет `@playwright/test`; зависимости фронта — в `frontend/package.json` (playwright как devDep там тоже может быть).