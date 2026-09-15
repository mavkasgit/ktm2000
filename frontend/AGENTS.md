# Frontend — KTM-2000

React 18.3 + TypeScript + Vite + Tailwind CSS + shadcn/ui + TanStack Query/Virtual.

## FSD (Feature-Sliced Design)

Слои: `app` → `features` → `entities` → `shared`.

Слой `src/modules/` — переносимые модули (`notifications`, `user-settings`), потребляемые host-адаптерами из `features` через alias `@/modules/*`.

- **Запрещены** cross-imports между features одного слоя.
- Общее — спускать в `entities` или `shared`.
- Роутер: [`src/app/Router.tsx`](src/app/Router.tsx).

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