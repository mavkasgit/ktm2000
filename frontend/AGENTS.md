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