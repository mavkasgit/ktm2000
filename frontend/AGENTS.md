# Frontend — KTM-2000

React 18.3 + TypeScript + Vite + Tailwind CSS + shadcn/ui + TanStack Query/Virtual.

## FSD (Feature-Sliced Design)

Слои: `app` → `features` → `entities` → `shared`.

Слой `src/modules/` — переносимые модули (`notifications`, `user-settings`), потребляемые host-адаптерами из `features` через alias `@/modules/*`.

- **Запрещены** cross-imports между features одного слоя.
- Общее — спускать в `entities` или `shared`.
- Роутер: [`src/app/Router.tsx`](src/app/Router.tsx).

## Разделы и загрузка кода

- Страница раздела подключается **только** через `lazyPage`
  ([`src/app/lazyRoute.tsx`](src/app/lazyRoute.tsx)). Статический импорт
  страницы в [`src/app/Router.tsx`](src/app/Router.tsx) возвращает все разделы
  в начальный пакет (до #199 — 2 538 КБ); порог держит шаг гейта
  `frontend-build`.
- Ссылка на модуль страницы — **по файлу страницы**
  (`import("../features/references/pages/ProductsPage")`). Барелы
  `features/references`, `features/planning` и `features/admin` удалены: `tsc`
  не даёт вернуть путь, которым начальный пакет снова раздувается.
- Граница `Suspense` живёт один раз — на `<Outlet />` в
  [`src/app/Layout.tsx`](src/app/Layout.tsx) и на маршрутах вне каркаса
  (`/login`, `/auth/callback`). Своя граница на странице — нельзя: забытая
  граница показывает белый экран.
- Пока едет чанк, видно `RoutePending`. Обзор (`DashboardPage`) остаётся в
  начальном пакете: это первый экран.
- Флаг `future={{ v7_startTransition: true }}` у `RouterProvider`
  ([`src/app/main.tsx`](src/app/main.tsx)) нельзя снимать: без него переход в
  незагруженный раздел синхронный, React прячет прежний раздел с фокусом и
  рисует фолбэк.
- Термин — [ADR-0039](../docs/adr/0039-stranica-razdela-prishodit-svoim-chankom.md)
  и [GLOSSARY.md](../GLOSSARY.md).
- **Почему так, замеры и механика начального пакета** —
  [`docs/frontend/code-splitting.md`](../docs/frontend/code-splitting.md)
  (читать при правке `Router.tsx`, `lazyRoute.tsx`, `main.tsx` или порога
  `bundle-size-baseline.json`).

## Свежесть данных

- Списки и карточки читаются **только** через `useQuery` из
  [`@tanstack/react-query`](https://tanstack.com/query). Список в локальном
  `useState` с `useEffect(load)` — дрейф: экран не видит чужих изменений и не
  сообщает о своих.
- После мутации экран зовёт `invalidateAfter` из
  [`src/shared/api/cacheInvalidation.ts`](src/shared/api/cacheInvalidation.ts)
  с бизнес-действием. **Прямой `invalidateQueries` в фиче запрещён**: так
  разошлись списки ключей и появился баг «строка видна только после F5». Какие
  домены задевает действие — матрица `CACHE_ACTIONS`.
- Ключи берутся из фабрики
  [`src/shared/api/queryKeys.ts`](src/shared/api/queryKeys.ts), а не пишутся
  литералами.
- Глобальный `staleTime` равен интервалу опроса — 12 с
  ([`src/app/main.tsx`](src/app/main.tsx)). Длинный `staleTime` не чинит
  свежесть, а прячет забытую инвалидацию.
- [ADR-0041](../docs/adr/0041-reestr-sbrosa-kesa-i-stale-time.md).
- **Почему 12 с, роль возврата фокуса, история «только после F5»** —
  [`docs/frontend/data-freshness.md`](../docs/frontend/data-freshness.md)
  (читать при правке `cacheInvalidation.ts` / `queryKeys.ts` / `main.tsx` или
  жалобе на несвежие данные).

## Таблицы

Обоснования, история инцидентов и развёрнутые примеры —
[`docs/frontend/tables.md`](../docs/frontend/tables.md). **Читать перед правкой
таблицы, описания колонки, ряда фильтров, тулбара, массового режима или
порядка группированного списка.**

- **Компактная строка** — `TABLE_ROW_COMPACT`
  ([`src/shared/lib/dataTableStyles.ts`](src/shared/lib/dataTableStyles.ts)).
  Новая таблица берёт общий набор; свои уточнения объявляет рядом с собой и
  разворачивает поверх (`{ ...TABLE_ROW_COMPACT, ...overrides }`). Свои `p-2`,
  `size="sm"` и `rowHeight={…}` рядом с таблицей — нельзя.
  [ADR-0030](../docs/adr/0030-komaktnaya-stroka-i-utochneniya-tablits.md),
  [GLOSSARY.md](../GLOSSARY.md).
- **Экран не в общем стиле не заводит отдельную задачу (#311):** его приводят
  к общему набору в той же правке, где его и так трогают. Перечень и причины —
  #311, карта — [`docs/night/tickets/R-13.md`](../docs/night/tickets/R-13.md) §6.1.
- **Кнопка возврата** — `BackButton`
  ([`src/shared/ui/BackButton.tsx`](src/shared/ui/BackButton.tsx)): безымянная
  иконка слева от заголовка в `page-header`. Своя стрелка с текстом «Назад к …»,
  `Link`-подобная ссылка и `window.history.back()` — нельзя: `history.back()`
  при прямом заходе не делает ничего. Имя — в `aria-label`, раздел — в `title`.
  Не путать с «Назад» внутри мастеров (там шаг, а не маршрут).
- **Описание колонки** — семантика объявляется один раз в
  [`src/shared/lib/columnSpecs.ts`](src/shared/lib/columnSpecs.ts)
  (`ColumnSpec`: `filterField`, `sortField`, `valueLabel`, `exactMatch`,
  `apiParam`, `mapValue`, `toParams`, `paramKind`, `clientOnly`); из него
  порождаются шапка, фильтр, сортировка и параметры запроса. Тернарники,
  `pickExactMatchColumnValue`, своя `buildXColumnApiParams`, прямой
  `SortableFilterHeader` и свой `handleSort` — нельзя: параметры собирает
  `buildColumnApiParams` (значения точного совпадения — он же), шапку решает
  [`DataTableColumnHeader.tsx`](src/shared/ui/DataTableColumnHeader.tsx), цикл
  направлений один — `nextMultiSortConfigs`. `defaultSort` объявляется хуку и
  возвращается сбросом. Колонка, которую сервер не фильтрует, — **без**
  `filterField`/`sortField`. Колонка, которую фильтрует сам экран, —
  `clientOnly: true` (попапер есть, значение уходит в предикат по загруженным
  строкам; расхождение ловит тест «поповер есть, ключа в параметрах нет»).
- **Род значения** объявляет `paramKind` (`"string" | "number" | "boolean"`), а
  приводит `buildTypedColumnApiParams`. Ослаблять контракт до
  `number | string` и приводить значения руками на экране — нельзя.
- **Порядок группированных списков** — количество убыв., но одинаковые
  артикулы рядом: [`clusterByArticle.ts`](src/shared/lib/clusterByArticle.ts)
  (доска `SectionTasksBoard`, «Готово к передаче» `groupReadyTransfers`,
  печатный план `planTaskGroups`). Своя сортировка по `amount` — нельзя.
- **«Все ГХП» в «Готово к передаче»** — сначала блоки по ГХП
  (`groupReadyTransfersBySpg`, порядок справочника), внутри — артикульный
  (`groupReadyTransfers`). Шапка красится `icon_color`, «Без ГХП» — нейтральный
  тон. Выбранная сортировка колонки отключает группировку целиком.
- **«Откуда»/«Куда»** — печатается участок, операция через `·`
  (`stagePointLabel`); коды участков и номера этапов в ячейку не попадают.
  Порядок: ID → Артикул → Размер → К передаче → Откуда → Куда.
- **Ряд фильтров** — [`FiltersPanel.tsx`](src/shared/ui/FiltersPanel.tsx)
  (`compact`): поиск → печать → массовые операции, одной строкой на всех
  экранах со списком. Своя вёрстка ряда и свои `Input`/`Button` — нельзя.
  - **Печать** — `PrintButton` ([`PrintButton.tsx`](src/shared/ui/PrintButton.tsx))
    сразу после поиска, одна на все экраны; что печатается, решает страница
    (в лист уходит тот же набор колонок). Лист — `PrintStyles`
    ([`PrintSheet.tsx`](src/shared/ui/PrintSheet.tsx)): `print-area`,
    `print-sheet`, `no-print`. Свой `@media print` — нельзя.
  - **Массовые операции** — `kind: "bulk"`: «Групповые операции» + «Выделить
    все (N)». Чекбокс в шапке таблицы — нельзя; выбор виден на строке
    (`TABLE_ROW_STYLES.selectedRow`). Количество вводится и в строке, и в
    массовом режиме, кнопок передачи в строках нет — отправляет один футер;
    набранное живёт на странице (`readyRowIdentity`), а не в строке
    (виртуализация); шапка группы носит общее количество и раскладывает
    (`planTransferQuantities`), клик берёт группу, выбранная шапка красится
    (`selectedGroupHeader`). Нули из хвоста отправку не блокируют.
- **Пауза перед запросом по поиску** — `useDebouncedValue`
  ([`useDebouncedValue.ts`](src/shared/lib/useDebouncedValue.ts)): задерживается
  запрос, а не ввод. Для `Enter` = «искать сейчас» — `useFlushableDebouncedValue`
  (тот же хук с `flush`, не вторая реализация). Свой `setTimeout` — нельзя.

## Подпись размера

- Колонка «Размер» печатается **только** через `formatDimensionsLabel`
  ([`src/shared/api/stock.ts`](src/shared/api/stock.ts)): «2,7 м», «—» для
  безразмерных. Правило общее с бэкендом
  (`backend/app/domain/dimensions.py::format_dimensions`).
- Второй аргумент — готовая серверная подпись того же правила, а не запасной
  путь; сборка подписи на месте (`dimensions_label ?? formatDimensionsLabel(…)`,
  `dimensions_label || "—"`) запрещена. «—» означает, что габарита
  действительно нет. [ADR-0035](../docs/adr/0035-edinoe-imenovanie-razmera.md),
  [GLOSSARY.md](../GLOSSARY.md).
- **История расхождения «—» против «2,75 м»** —
  [`docs/frontend/quantity.md`](../docs/frontend/quantity.md) (читать при правке
  ячейки или подписи размера).

## Ввод количества

- Поле количества в операции — **только целые штуки**: запятая, точка и минус
  отклоняются с видимой причиной под полем, ноль допустим, пустое поле —
  отсутствие ввода, а не ноль. Правило живёт один раз в
  [`quantityInput.ts`](src/shared/lib/quantityInput.ts) (`normalizeQuantityInput`:
  цифры + причина отклонения); своя регулярка рядом с полем — нельзя.
- **Не распространяется** на дробные по домену места: передачи (`Numeric(14,3)`),
  количество на подвес, справочник сырья, превью плана.
- Разбор чисел в коде (`parseNumericInput`, `Number`, `parseFloat`) **проницаем**
  и ничем не ограничен: правило — на вводе оператора, не в вычислениях
  (значения из БД вида `200.0` читаются как есть).
- Кнопку подтверждения дизейблить нельзя: причина видна без наведения.
  [ADR-0032](../docs/adr/0032-edinoe-pravilo-vvoda-kolichestva.md),
  [GLOSSARY.md](../GLOSSARY.md).

### Правка записанного факта

- **Другое** правило — [`correctedQuantityInput.ts`](src/shared/lib/correctedQuantityInput.ts)
  (`normalizeCorrectedQuantityInput`): дробь **законна**, ноль **запрещён**.
  Единый модуль на оба случая — ошибка.
- На сервер уходит **число**, не строка (`Decimal("5,5")` бросает исключение):
  запятая и точка приравниваются, поле хранит набранное; точность — не больше
  трёх знаков. Верхнего лимита на клиенте нет (покрытие склада считает
  предпросмотр; лимит задачи давал ложные отказы на `allow_over_plan`).
  [ADR-0036](../docs/adr/0036-pravilo-vvoda-kolichestva-pri-pravke-fakta.md),
  [GLOSSARY.md](../GLOSSARY.md).

## Вывод количества

- Количество печатает **только** [`quantityFormat.ts`](src/shared/lib/quantityFormat.ts).
  Своя копия, `toFixed(0)` в ячейке, `String(Math.round(…))` — нельзя (до #201
  форматеров было девять).
- **Домена два.** `fmtQty` — целые штуки: доска, задание и его кэш (план,
  выдано, годные, брак, передано, остаток), передачи, склад и журнал движений,
  печать плана, дневные итоги. `fmtQtyPrecise` — живая дробь: количество на
  подвесе и нормы в справочниках, состав ГП, превью плана (иначе `2,5` стало бы
  `3`).
- **Подвесы — счётчик:** `countHangers` в
  [`hangerCount.ts`](src/shared/lib/hangerCount.ts), округление вверх. Значение
  из БД в целое — `toQtyInteger` (своя `Math.round(parseFloat(…))` — нельзя).
- **Разделитель тысяч запрещён** — e2e разбирает `(\d+)\s*шт`; поэтому
  передачи печатаются целыми, хотя колонка дробная. **Разделитель — запятая**,
  3 знака, хвостовые нули срезаются; на **выводе** разбор строго числовой
  (строка с запятой — `QTY_EMPTY`), «запятая равна точке» — только про ввод
  (ADR-0036).
- **Не-число → `QTY_EMPTY` («—»)** и в таблице, и в списке фильтра: «0» стирает
  разницу «нет значения»/«ноль», сырая строка печатает несуществующее; ячейка и
  фильтр берут один форматтер. [ADR-0040](../docs/adr/0040-edinyy-format-vyvoda-kolichestva.md),
  [GLOSSARY.md](../GLOSSARY.md).
- **Домены, история #201 и примеры** —
  [`docs/frontend/quantity.md`](../docs/frontend/quantity.md) (читать при правке
  форматтера или нового экрана, который печатает количество).

## Окна

- Новое окно берёт **каркас** `Dialog`
  ([`src/shared/ui/dialog.tsx`](src/shared/ui/dialog.tsx)): оверлей,
  центрирование, фокус, `Escape`, блокировка прокрутки, подписи. Свой оверлей,
  свой `role="dialog"` и свой `keydown` для `Escape` — нельзя.
- Размер — из `DIALOG_SIZES`
  ([`dialogSizes.ts`](src/shared/lib/dialogSizes.ts)): `sm` — подтверждение и
  короткая форма, `md` — настройки, `wide` — таблицы и печать. Свои
  `max-w-[…]` — нельзя; уточнения — рядом с собой и поверх набора.
- Заголовок — `DialogTitle`, пояснение — `DialogDescription`. Свой крестик и
  `aria-label` на безымянном `div` — нельзя.
- Глобальный обработчик клавиш страницы **спрашивает `isAnyDialogOpen()`**
  ([`dialogOpen.ts`](src/shared/lib/dialogOpen.ts)), а не флаги состояния:
  флаги забывают новое окно, и `Escape` работает поверх открытого окна.
- [ADR-0033](../docs/adr/0033-obshchiy-karkas-modalnyh-okon.md) и
  [GLOSSARY.md](../GLOSSARY.md).
- **Почему нельзя свой оверлей и чем это заканчивалось** —
  [`docs/frontend/dialogs.md`](../docs/frontend/dialogs.md) (читать перед
  созданием или правкой окна, панели, подтверждения).

## Прототипы UI

- Перед макетом или прототипом экрана — открыть **реальный** экран в dev-стенде
  и прочитать реальный компонент: прототип по памяти воспроизводит экран,
  которого нет.
- Окно прототипируют по **фактической структуре**, а не «панелью с полями»
  (пример — карточка артикула
  [`CatalogForm.tsx`](src/features/references/components/CatalogForm.tsx): фото
  320 px, поля в три колонки, размерность и нормы, «Пары», «Примечания», футер).
- Правила конкретного экрана живут здесь: глобальный скилл
  `~/.agents/skills/prototype` общий и теряет локальные пометки при обновлении.
- **Развёрнутый пример карточки артикула и почему прототип по памяти вреден** —
  [`docs/frontend/ui-prototypes.md`](../docs/frontend/ui-prototypes.md) (читать
  перед макетом или перерисовкой экрана, окна, карточки).

## Команды

```bash
npm --prefix frontend run dev       # :5172
npm --prefix frontend run build
npm --prefix frontend run lint      # ESLint (в т.ч. архитектурные границы FSD)
npm --prefix frontend run lint:ratchet  # ESLint + потолок предупреждений (то, что зовёт гейт, #372)
npm --prefix frontend run lint:strict   # eslint . --max-warnings=0 (цель, пока красный: 47 предупреждений)
npm --prefix frontend run test      # Vitest unit-тесты
npm --prefix frontend run test:e2e  # Playwright E2E
```

Точечные проверки — **из каталога `frontend/`**, пути считаются от него:

```bash
cd frontend
npx eslint src/features/spg/ImportRemaindersDialog.tsx   # файл или каталог
npx vitest run src/shared/lib/quantityFormat.test.ts     # файл или каталог
```

`npm --prefix frontend exec -- eslint <путь>` резолвит путь от **корня
репозитория** и падает («No files matching the pattern "src/…"»): либо `cd
frontend`, либо путь от корня (`frontend/src/…`).

## E2E (Playwright)

Канон → [`e2e/AGENTS.md`](e2e/AGENTS.md): предусловия, env, фикстуры, спеки.

```bash
npm --prefix frontend run test:e2e   # стенд поднимается сам: своя БД и свои порты
```

Ручной `npm run dev` для прогона **не нужен** (и не переиспользуется молча:
`reuseExistingServer: false`). Он требуется только в отладочном сценарии
`PW_REUSE_STACK=1`, когда прогон идёт против уже поднятого стека — см.
[`e2e/AGENTS.md`](e2e/AGENTS.md).
