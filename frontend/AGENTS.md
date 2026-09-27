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