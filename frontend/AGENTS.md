# Frontend — KTM-2000

React 18.3 + TypeScript + Vite + Tailwind CSS + shadcn/ui + TanStack Query/Virtual.

## FSD (Feature-Sliced Design)

Слои: `app` → `features` → `entities` → `shared`.

Слой `src/modules/` — переносимые модули (`notifications`, `user-settings`), потребляемые host-адаптерами из `features` через alias `@/modules/*`.

- **Запрещены** cross-imports между features одного слоя.
- Общее — спускать в `entities` или `shared`.
- Роутер: [`src/app/Router.tsx`](src/app/Router.tsx).

## Таблицы

- **Компактная строка** — высота строки, отступы ячеек, размер кнопки действия
  и бейджа берутся из `TABLE_ROW_COMPACT`
  ([`src/shared/lib/dataTableStyles.ts`](src/shared/lib/dataTableStyles.ts)).
  Новая таблица берёт общий набор; свои уточнения объявляет рядом с собой и
  разворачивает поверх (`{ ...TABLE_ROW_COMPACT, ...overrides }`).
  Свои `p-2`, `size="sm"` и `rowHeight={…}` рядом с таблицей — нельзя.
  Термин и правило — [ADR-0030](../docs/adr/0030-komaktnaya-stroka-i-utochneniya-tablits.md)
  и [CONTEXT.md](../CONTEXT.md).

- **Описание колонки** — семантика колонки объявляется один раз в
  [`src/shared/lib/columnSpecs.ts`](src/shared/lib/columnSpecs.ts)
  (`ColumnSpec`): `filterField`, `sortField`, `valueLabel`, `exactMatch`,
  `apiParam`, `mapValue`, `toParams`, `clientOnly`. Из описания порождаются
  шапка, фильтр, сортировка и параметры запроса. Тернарник
  `filterField === "dimensions"` в шапке и ручной вызов
  `pickExactMatchColumnValue(…, "dimensions")` — не способ объявить
  семантику: добавить колонку с особым фильтром значило бы править и то и
  другое. Значения точного совпадения собирает `exactMatchColumnParams`.
  Своя функция `buildXColumnApiParams` с перечислением колонок — не способ
  собрать параметры: используйте `buildColumnApiParams`, он берёт колонки из
  описания.
  Шапка собирается компонентом
  [`src/shared/ui/DataTableColumnHeader.tsx`](src/shared/ui/DataTableColumnHeader.tsx):
  фильтр, сортировка, фильтр-без-сортировки, сортировка-без-фильтра и голая
  подпись — его решение. Тернарник `filterField ? … : <span>` в разметке
  экрана означает, что случай ещё не покрыт общим компонентом.
  Сортировка по умолчанию объявляется хуку (`defaultSort`) и сбросом
  возвращается, а не считается фильтром: условие «сортировка нестандартная»,
  написанное руками, расходилось между экранами.
  Колонка, которую сервер не фильтрует, объявляется **без** `filterField` и
  `sortField`, а не с флагом, который ничего не отправляет.
- **Пауза перед запросом по поиску** — [`src/shared/lib/useDebouncedValue.ts`](src/shared/lib/useDebouncedValue.ts).
  Свой `useState` + `useEffect` с `setTimeout` рядом с полем — нельзя: таких
  копий было двенадцать, и одна цифра в задержке меняла поведение одного
  экрана. Поле хранит введённое значение, задерживается запрос, а не ввод.
  Для поля, где `Enter` означает «искать сейчас», — `useFlushableDebouncedValue`
  (тот же хук с выходом `flush`, а не вторая реализация).

## Подпись размера

- Колонка «Размер» печатается **только** через `formatDimensionsLabel`
  ([`src/shared/api/stock.ts`](src/shared/api/stock.ts)): «2,7 м», «—» для
  безразмерных. Правило общее с бэкендом
  (`backend/app/domain/dimensions.py::format_dimensions`).
- Второй аргумент — готовая серверная подпись того же правила, а не запасной
  путь. Сборка подписи на месте запрещена: `dimensions_label ??
  formatDimensionsLabel(…)` и `dimensions_label || "—"` печатали для одного
  размера разные строки. Доска считает подпись сама (в её ответе нет
  `dimensions_label`), план и передачи берут готовую — расхождение было видно
  как «—» против «2,75 м» в соседних экранах.
- «—» означает, что габарита действительно нет. Термин и правило —
  [ADR-0035](../docs/adr/0035-edinoe-imenovanie-razmera.md) и
  [CONTEXT.md](../CONTEXT.md).

## Ввод количества

- Поле количества в операции — **только целые штуки**: запятая, точка и минус
  отклоняются с видимой причиной под полем, ноль допустим, пустое поле
  означает отсутствие ввода, а не ноль. Правило живёт один раз в
  [`src/shared/lib/quantityInput.ts`](src/shared/lib/quantityInput.ts)
  (`normalizeQuantityInput`): функция возвращает оставшиеся цифры и причину
  отклонения, поле само решает, где её показать. Своя регулярка
  `replace(/[^\d]/g, "")` рядом с полем — нельзя.
- **Не распространяется** на дробные по домену места: передачи
  (`Numeric(14,3)`), количество на подвес, справочник сырья, превью плана.
- Разбор чисел в коде (`parseNumericInput`, `Number`, `parseFloat`) при этом
  **остаётся проницаемым** и ничем не ограничен: правило живёт на вводе
  оператора, а не в вычислениях. Значения из БД вида `200.0` читаются как есть.
- Кнопку подтверждения дизейблить нельзя: причина должна быть видна без
  наведения. Термин и правило — [ADR-0032](../docs/adr/0032-edinoe-pravilo-vvoda-kolichestva.md)
  и [CONTEXT.md](../CONTEXT.md).

### Правка записанного факта

- Это **другое** правило, и оно живёт в
  [`src/shared/lib/correctedQuantityInput.ts`](src/shared/lib/correctedQuantityInput.ts)
  (`normalizeCorrectedQuantityInput`). Здесь дробь **законна**, а ноль
  **запрещён** — ровно наоборот с предыдущим разделом.
- Причина та же, что у ADR-0032: правка применяется к `transfer_send`, а
  передачи дробные (`Numeric(14,3)`), и сервер требует строго больше нуля.
  Единый модуль на оба случая — ошибка: в одной половине мест дробь
  законна, в другой запрещена, и импортируется не то.
- На сервер уходит **число**, а не строка: `Decimal("5,5")` бросает
  исключение, поэтому запятая и точка приравниваются, а поле хранит то, что
  набрал оператор. Точность — не больше трёх знаков после запятой.
- Верхнего лимита на клиенте не вводим: покрытие склада считает
  предпросмотр, а лимит задачи уже давал ложные отказы на трансформирующих
  этапах (`allow_over_plan`).
- [ADR-0036](../docs/adr/0036-pravilo-vvoda-kolichestva-pri-pravke-fakta.md)
  и [CONTEXT.md](../CONTEXT.md).

## Окна

- Новое окно берёт **каркас** `Dialog`
  ([`src/shared/ui/dialog.tsx`](src/shared/ui/dialog.tsx)): оверлей,
  центрирование, удержание фокуса, закрытие по `Escape`, блокировку прокрутки,
  возврат фокуса и подписи он даёт сам. Свой оверлей
  `fixed inset-0 bg-black/…`, свой `role="dialog"` и
  `window.addEventListener("keydown", …)` для `Escape` — нельзя: это ровно то,
  из-за чего окна ведут себя по-разному.
- Размер окна — из `DIALOG_SIZES`
  ([`src/shared/lib/dialogSizes.ts`](src/shared/lib/dialogSizes.ts)):
  `sm` — подтверждение и короткая форма, `md` — панель настроек, `wide` —
  таблицы и печать. Свои `max-w-[…]` рядом с окном — нельзя; уточнить можно
  только рядом с собой и поверх общего набора.
- Заголовок окна — `DialogTitle`, пояснение — `DialogDescription`. Свой
  крестик и `aria-label` на безымянном `div` — нельзя: имя окна для чтения с
  экрана берётся из самого текста.
- Глобальный обработчик клавиш страницы **спрашивает `isAnyDialogOpen()`**
  ([`src/shared/lib/dialogOpen.ts`](src/shared/lib/dialogOpen.ts)), а не флаги
  состояния: перечисление окон флагами забывает новое окно, и `Escape` начинает
  работать поверх открытого окна.
- Термин и правило — [ADR-0033](../docs/adr/0033-obshchiy-karkas-modalnyh-okon.md)
  и [CONTEXT.md](../CONTEXT.md).

## Команды

```bash
npm --prefix frontend run dev       # :5172
npm --prefix frontend run build
npm --prefix frontend run test      # Vitest unit-тесты
npm --prefix frontend run test:e2e  # Playwright E2E
```

## E2E (Playwright)

Канон → [`e2e/AGENTS.md`](e2e/AGENTS.md): предусловия, env, фикстуры, спеки.

```bash
npm run dev                              # сначала из корня
npm --prefix frontend run test:e2e
```