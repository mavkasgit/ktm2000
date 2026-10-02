# T-253 — серия `--workers=2` на `smoke + ui-narrow` (10 прогонов) (#253)

- **Статус:** DONE — замер сделан, вердикт: `workers: 1` остаётся (правок нет)
- **Ветка/дерево:** `night/2026-10-01-e`, `C:/Users/LogoPrint/VibeCoding/ktm2000-night-e`
- **SHA на момент серии:** `7c269e50dddc6c09e7e48d4d0fd71dea90eec038`
- **Стенд:** `E2E_ENV_FILE=.env.e2e.night-e.local` (namespace `ktm2000_e2e_night_e`),
  семафор `E2E_MAX_PARALLEL_RUNS=1`; каждый прогон — свой клон шаблонной БД (#281).
- **Команда:**
  `npm --prefix frontend run e2e:run -- ui-narrow --project smoke --workers=<N> --retries=0`
  (`playwright test --project ui-narrow --project smoke`; оба проекта в прогоне, 10 тестов).
- **`retries`:** `0` явно. **`CI`:** окружение харнесса выставляет `CI=true`;
  для каждого прогона переменная переопределена пустой (`CI=`), то есть в
  Playwright falsy (`retries` из конфига = 0).
- **Нагрузка:** dev-стек человека (`:5172`, `:8012`), прод-контейнеры и **чужая
  сессия в основном дереве** (`ktm2000`, продукт #283 + периодический `vitest run`) —
  все замеры **под нагрузкой**, эталоном времени не являются. Проверка чужих
  процессов дополнена `vitest`:
  `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pytest|vitest|run-tier|run-e2e\.mjs|playwright' }`.

## Подмножество

`smoke` + `ui-narrow` = 10 тестов: smoke (`catalog-create`, `catalog-dimensions`,
`dimensions-sawing`, `final-release`, `reversal-journal`, `transfers-auto-accept`)
+ ui-narrow (`sawing-four-lengths-cycle`, `sawing-multi-length-split`,
`yup460-shared-raw-pile`).

## Контрольная точка: `workers=1` (дефолт `playwright.config.ts`)

| # | wall внешний | wall яруса | Итог | Чужая нагрузка |
|---|---|---|---|---|
| b1 | 326 с | 324 с | 10 passed | проверка перед стартом пуста |
| b2 | 229 с | 228 с | 10 passed | проверка перед стартом пуста (ждал чужой pytest) |

Сумма двух последовательных прогонов: **555 с** (среднее 277 с).

## Серия `workers=2` — 10 прогонов

| # | wall внешний | wall яруса | rc | Итог | Упавшие тесты |
|---|---|---|---|---|---|
| 1 | 62 с | 61 с | 1 | 2 failed / 8 passed | `final-release`, `sawing-four-lengths-cycle` |
| 2 | 63 с | 61 с | 1 | 2 failed / 8 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| 3 | 53 с | 51 с | 1 | 2 failed / 8 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| 4 | 63 с | 61 с | 1 | 2 failed / 8 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| 5 | 65 с | 63 с | 1 | 2 failed / 8 passed | `final-release`, `sawing-four-lengths-cycle` |
| 6 | 63 с | 62 с | 1 | 3 failed / 7 passed | `sawing-four-lengths-cycle`, `sawing-multi-length-split`, `yup460-shared-raw-pile` |
| 7 | 61 с | 59 с | 1 | 3 failed / 7 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle`, `sawing-multi-length-split` |
| 8 | 62 с | 60 с | 1 | 3 failed / 7 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle`, `yup460-shared-raw-pile` |
| 9 | 280 с | 279 с | 1 | 2 failed / 8 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle` **(загрязнён: чужая нагрузка)** |
| 10 | 65 с | 61 с | 1 | 2 failed / 8 passed | `transfers-auto-accept`, `sawing-four-lengths-cycle` |

Машина перед стартом каждого прогона была свободна (проверка пуста); mid-run
нагрузка в этой серии не инструментировалась — поэтому прогон 9 (280 с против
~61 с) помечен как вероятно загрязнённый.

### Контрольная выборка с поштучной разметкой нагрузки (mid-run сэмплинг)

Повтор той же серии с сэмплингом процессов раз в 10 с во время прогона:

| # | wall внешний | rc | Итог | Машина | Упавшие тесты |
|---|---|---|---|---|---|
| m1 | 64 с | 1 | 2 failed / 8 passed | тихо | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| m2 | 64 с | 1 | 2 failed / 8 passed | тихо | `final-release`, `sawing-four-lengths-cycle` |
| m3 | 64 с | 1 | 2 failed / 8 passed | тихо | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| m4 | 75 с | 1 | 2 failed / 8 passed | тихо | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| m5 | 64 с | 1 | 3 failed / 7 passed | тихо | `transfers-auto-accept`, `sawing-four-lengths-cycle`, `sawing-multi-length-split` |
| m6 | 74 с | 1 | 2 failed / 8 passed | тихо | `sawing-four-lengths-cycle`, `sawing-multi-length-split` |
| m7 | 64 с | 1 | 2 failed / 8 passed | тихо | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| m8 | 65 с | 1 | 2 failed / 8 passed | **нагрузка: vitest** (основное дерево) | `transfers-auto-accept`, `sawing-four-lengths-cycle` |
| m9 | 472 с | 1 | вывод репортера потерян (465 с под vitest) | **нагрузка: vitest** | — |
| m10 | — | — | не запускался: машина занята vitest > 10 мин | нагрузка | — |

**Чистых прогонов (m1–m7): 7 из 7 — красные.** m8/m9 загрязнены чужой нагрузкой,
m10 не запускался.

## Частота падений

| Тест | Ярус | Первая серия (10) | Чистые m1–m7 (7) |
|---|---|---|---|
| `sawing-four-lengths-cycle` | ui-narrow | 10/10 | 7/7 |
| `transfers-auto-accept` | smoke | 7/10 | 4/7 |
| `final-release` | smoke | 2/10 | 1/7 |
| `sawing-multi-length-split` | ui-narrow | 2/10 | 2/7 |
| `yup460-shared-raw-pile` | ui-narrow | 2/10 | 0/7 |

Профиль почти в точности повторяет замер на **общей** БД (10/10 красных:
`sawing-four-lengths-cycle` 10/10, `transfers-auto-accept` 7/10, `final-release` 3/10,
`sawing-multi-length-split` 3/10). Вывод: изоляция #281 — **на прогон**, а не на
воркер, и поведения `workers=2` внутри прогона она не изменила.

## Вердикт

Критерий тикета («**0 флейков** И суммарное время меньше последовательного») **не
выполнен**: `--workers=2` красный в 10/10 прогонов первой серии и 7/7 чистых
прогонов повторной выборки. Ускорение реально и велико (228–326 с → 51–66 с), но
непригодно. **`workers: 1` в `frontend/playwright.config.ts` остаётся; правок
нет, коммита нет.**

Механизм. `--workers=2` распараллеливает **файлы внутри одной фазы**, а проекты
`smoke` и `ui-narrow` при выбранной команде идут **одновременно** (цепочка
`dependencies` разбивает проекты на фазы только на `all` и при `--no-deps`
снята). Клон БД у прогона один, а `apiResetAll()` в `beforeEach` — `TRUNCATE …
CASCADE` по 27 таблицам: воркер smoke сносит данные, пока ui-narrow идёт по
длинному сценарию, и наоборот. Отсюда:
- `element(s) not found` по `tr[data-row-key=…]` / строке «Готово к передаче»;
- `Error: No active import template found` (`api-helpers.ts:280`) — снесены сиды.

`dependencies` при `--workers=2` не помогают: они разбивают проекты на фазы, но
внутри фазы воркеры конкурируют за одну БД. Чтобы `workers=2` стал пригоден,
нужна изоляция **по воркеру** (своя БД/схема на воркер) или принудительная
сериализация проектов; изоляция «клон на прогон» (#281) этого класса не закрывает.

## Артефакты

- Логи: `docs/night/logs/T-253-baseline-{1,2}.log`, `T-253-w2-{1..10}.log`,
  `T-253-w2m-{1..9}.log` (каталог gitignored).
- Прогон 9 первой серии и m8/m9 — загрязнены чужой нагрузкой (`vitest` из
  основного дерева); m10 не запускался.
