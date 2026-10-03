# T-308 — единый раздел «Журнал»: один пункт меню, вкладки, кнопка возврата

Срез: `night/2026-10-03-a`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night-a`.
Коммиты: `41b7824`, `3c62775`, merge main → `2af9c51`.

## Что сделано

- `app/Layout.tsx`: в `navItems` один пункт `{ to: "/audit-logs", label: "Журнал", icon: History }`,
  пункт «Отмена действий» удалён, импорт `Undo2` убран из списка lucide.
- Новый `shared/ui/JournalTabs.tsx` (+ экспорт в `shared/ui/index.ts`): сегментированный
  переключатель `NavLink` «Действия» → `/audit-logs` | «Отмена действий» → `/reversal`,
  активная вкладка подсвечивается по маршруту. Вне контекста роутера рендерит обычные
  `<a>` — страницу можно unit-тестировать без обёртки-роутера.
- `reversal/pages/ActionsJournalPage.tsx`: свой `<h1 className="text-xl font-bold text-slate-800">`
  заменён на `page-header` / `page-title` / `page-subtitle`, добавлены `JournalTabs` и
  `BackButton to="/audit-logs"` (рендерится только внутри роутера: `useNavigate` вне него
  бросает инвариант, а `ActionsJournalPage.test.tsx` рендерит страницу без роутера).
- `sections/pages/AuditLogsPage.tsx`: в шапку добавлен `JournalTabs`. Классы строк/панели/тонов
  не тронуты (зона среза C).
- `e2e/reversal-journal.spec.ts`: шаг 1 — клик по «Журнал» в боковом меню → клик по вкладке
  «Отмена действий» → URL `/reversal` → заголовок «Отмена действий». Селекторы меню/вкладок
  уточнены до landmark (`navigation "Основная навигация"`, `navigation "Разделы журнала"`),
  иначе строка вкладки совпадала бы с пунктом меню.

## Побочные правки (вне скоупа, но блокировали приёмку)

- `e2e/run-lock.mjs`: `reclaimReason` падал с `TypeError: now is not a function` —
  дефолт был `now = Date.now()`, а вызов `now()`. Падало **любое** e2e-приложение.
  Исправлено на `now = () => Date.now()` (баг от #281, в `main`).
- `e2e/reversal-journal.spec.ts`: селектор строки искал сырой код `manual_adjustment`,
  которого в UI больше нет (#117-era spec, сломан после локализации подписей). Заменён на
  локализованную подпись «Ручная корректировка остатка».

## Доказательства

| Гейт | Команда | Результат |
|---|---|---|
| Типы | `npx tsc -p tsconfig.json --noEmit` | `TSC_OK`, 0 ошибок (до и после merge main) |
| Юнит | `npm --prefix frontend run test` | `Test Files 156 passed \| 1 skipped (157)`, `Tests 1291 passed \| 1 skipped (1292)`, 0 failed |
| e2e ui | `CI='' E2E_MAX_PARALLEL_RUNS=3 npm --prefix frontend run test:e2e:ui` | EXIT=0, `13 passed (4.6m)`, workers=1, retries=0 (`CI` пуст → `retries: process.env.CI ? 2 : 0` = 0) |
| e2e smoke | `CI='' E2E_MAX_PARALLEL_RUNS=3 npm --prefix frontend run test:e2e:smoke` | EXIT=0, `7 passed (33.3s)`, включая `ok 6 reversal-journal.spec.ts` |
| ruff | `cd backend && ruff check .` | 1 ошибка `I001` в `app/seeds/canon/registry.py:110` — **предсуществующая**, Python не менялся; не чинил |

SHA на момент прогонов e2e: `41b7824` (ui) и `3c62775` (smoke, после фикса селектора).
Прогон с `CI=''` и `retries=0`, `workers=1` (`playwright.config.ts:146-147`).

## Не сделано

- `Router.tsx`, сиды ролей, backend не трогались (все шесть ролей уже содержат оба пути).
- Редиректов нет, маршруты `/audit-logs` и `/reversal` не менялись.
- Классы строк/панели/тонов в `AuditLogsPage.tsx`, `shared/lib/rowTones.ts`,
  `shared/ui/FiltersPanel.tsx`, остальной `features/sections/**` — зона среза C, не трогал.
- Предсуществующий `I001` в backend не чинил (Python этой ночью не правится).
