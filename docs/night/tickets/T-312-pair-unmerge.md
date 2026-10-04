# T-312 — снять склейку пар, индивидуальные задания, группировка и единый подвес

Срез: `night/2026-10-03-312`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night-312`.
Коммиты: `0a48f8f5` (код), `01a35331` (спека). Merge main → fast-forward на `ae897a0`.

## Сделано

### Backend — склейка снята

- `app/services/excel_import.py`: удалены `_can_join_as_paired_profile` и
  `_join_paired_component` вместе с веткой склейки в `_parse_rows`. Каждая строка
  листа — своя позиция плана со своим артикулом.
- `app/services/product_pair_resolver.py` (**обобщение, не удаление**): добавлены
  `resolve_pair_by_product_id`, `resolve_pair_n_for_product`, индекс справочника
  пар по `product_id` (`_load_pair_index_by_product`) и `PairResolutionCache.resolve_pair_by_product`.
  Прежние `resolve_pair_by_component_skus` / `resolve_effective_product_ids` /
  `resolve_pair_n` на месте — планы, импортированные до #312, продолжают работать.
- `app/services/plan_position_hanger.py`: норма позиции, чей артикул входит в пару,
  берётся у пары (`compute_paired_hanger_quantity`) — на подвесе едут оба
  компонента. Артикул вне пары и ручной override из payload идут прежним путём.
- `app/services/plan_import_service.py`: тот же резолв при импорте, справочник пар
  читается один раз на импорт (`PairResolutionCache`), округление количества идёт
  по парной N.

### Frontend — группировка и единый подвес

- `lib/planTaskGroups.ts`: `buildPlanPairIndex` + необязательный параметр `pairs`
  у `buildPlanTaskGroups`. В режиме `article` ключ группы у парных строк — пара
  (а не свой артикул), поэтому обе позиции печатаются вместе; строки при этом
  **не сливаются** — работа идёт по каждой отдельно. Подпись группы — «A+B · размер»,
  SKU берутся по ключу группы (пара + размер), а не по паре целиком.
- `components/PlanTaskTable.tsx`: у группы пары подвесы **не суммируются**, а
  берутся у пары (`ceil(max(planQty) / N)`); колонка «Кол-во на подвес» печатается
  как `8×ЮП-2604 + 8×ЮП-2616`. Колонки «Подвесы»/«Кол-во на подвес» сохранены.
- `components/PlanModal.tsx`: каталог пар грузится простым эффектом (без
  `useQuery` — иначе тесты окна требовали бы `QueryClientProvider`). Ошибка или
  отсутствие каталога оставляют печать прежней.

### Тесты

- `backend/tests/test_excel_import.py`: 8 тестов переписаны под новое поведение
  (2 позиции вместо склейки, своя норма пары у каждой позиции, выбор строки не
  тянет вторую, постраничность на 3 items).
- `backend/tests/test_demo_full_route.py`: демо-сценарий пары даёт две позиции.
- `frontend`: +8 тестов (`planTaskGroups.test.ts` — 5, `PlanTaskTable.test.tsx` — 3).
- `frontend/e2e/pair-article-cycle.spec.ts` (новая): полный цикл пары 2604/2616.
  Добавлен хелпер `apiCreateProductPair` в `e2e/api-helpers.ts`.

## Чем доказано

| Проверка | Результат |
|---|---|
| `pytest` (7 затронутых файлов) | **148 passed, 0 failed** (319,72 с) |
| `npx tsc -p tsconfig.json --noEmit` | 0 ошибок |
| `npx vitest run src/features/sections` | **282 passed** (29 файлов) |
| `npx @colbymchenry/codegraph sync` | Synced 153 файла, 3844 узла |

Полный `npm run test:pytest` и `npm run test:e2e` — см. раздел «Не сделано».

## Найдено по факту (issue разошёлся с кодом)

Issue предлагала «генерация плана: парная позиция → два набора `SectionPlanLine`/`WorkTask`».
**Это невозможно на текущей схеме**: `uq_section_plan_lines_stage`
(`internal_plan_id, plan_position_id, `route_stage_id`, миграция `006`) допускает
ровно одну строку на позицию и участок. Второй набор для того же `route_stage_id`
даёт `UniqueViolationError` (воспроизведено на `test_plan_generation.py`: две
парные позиции → `duplicate key value violates unique constraint
"uq_section_plan_lines_stage"`). Расширение ограничения задело бы и путь чтения
доски (`lines_by_pos_seq[(plan_position_id, sequence)]` в
`queries_sections.py:277` — один элемент на пару ключей, второй задание
потерялось бы).

AC при этом выполнены иначе: после снятия склейки пара — это **две позиции**, и
каждая естественно даёт свой набор `SectionPlanLine`/`WorkTask` на каждом участке,
включая анодирование. Правки `plan_generation.py` не потребовались, файл не тронут.
## Чем доказано

Второе окно (после merge `main`):

| Проверка | Результат |
|---|---|
| спека `pair-article-cycle.spec.ts` | **1 passed (3,7 мин)**, код 0 |
| `npm run test:e2e` (полный, `--retries=0 --workers=1`) | **код 0**, 854 с, `status: passed`, `failedTests: []` |
| `pytest` по своей зоне (7 файлов) | **148 passed** (301,72 с) |
| `pytest` точечно после merge R05 | **80 passed** (31,33 с) |
| `npx tsc -p tsconfig.json --noEmit` | 0 ошибок |
| `npx vitest run src/features/sections` | **282 passed** (29 файлов) |
| `npm run test:pytest` (полный, до merge) | **2077 passed, 2 skipped** (525,23 с) |
| `npx @colbymchenry/codegraph sync` | Synced 153 файла, 3844 узла |

Прогон e2e: `E2E_MAX_PARALLEL_RUNS=3`, `--retries=0`, `--workers=1`, `CI=` (пусто),
`E2E_ENV_FILE=.env.e2e.night-312.local`.

Что показала спека по шагам:

- `plan: 2 позиции, склейки нет` — ассерт на `[id^="plan-position-"]` даёт ровно
  2 строки, обе содержат свой артикул, ни одна не содержит `+`. **Эталон №1.**
- Импорт завёл маршрут каждому артикулу отдельно: лог стенда
  `Final route_id for row ЮП-2604: 5` и `Final route_id for row ЮП-2616: 5`.
- `ЮП-2604 отгружен`, `ЮП-2616 отгружен` — `[expectShipped] SKU=ЮП-2616 на
  «Отправлено»: 152 шт`. 152 = 19 подвесов × 8: количество округлено импортом
  по **парной** N (иначе было бы 150) — норма пары доехала до каждой позиции.
- Каждая позиция шла своим кругом передач (6 шагов маршрута, финальный раунд
  `передано 0, до «Отправлено» (шагов 6)`) — маршруты не слились. **Эталон №2.**

### Попутно найдено

`frontend/tsconfig.json` покрывает **только `src/`** — спеки e2e он не проверяет.
Первый прогон упал на `SyntaxError` в спеке (`{ name: "План", { exact: true } }`),
который `tsc` не увидел. Исправлено в `d68aa22e`; спека проверяется отдельной
командой `npx tsc --noEmit --strict … e2e/<спека>.ts`. Стоит завести
`tsconfig.e2e.json` — вне скоупа #312.

## Не сделано

- **AC «две строки пары сгруппированы на экране планов»** — не реализован.
  Группировка сделана на листе печати (`PlanTaskTable`/`planTaskGroups`, покрыта
  юнит-тестами), экран позиций плана (`features/planning/**`) не трогал: он вне
  зоны файлов тикета, и отдельного продуктового решения по его виду в issue нет.
  Уходит в утренний грилл-тикет.

## Следующий шаг

1. Закрыть #312 со стороны кода — спека и полный e2e зелёные.
2. Решить по экрану позиций плана (AC «группировка на экране планов»): либо
   довести группировку до `features/planning/**`, либо снять AC как неприменимый.
3. Обновить ADR-0023/0024: склейка пары на импорте больше не механика, а парная N
   и печатный подвес остаются.