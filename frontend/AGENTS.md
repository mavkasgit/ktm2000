# Frontend — KTM-2000

React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + TanStack Table/Query.

## FSD (Feature-Sliced Design)

Слои: `app` → `features` → `entities` → `shared`.

- **Запрещены** cross-imports между features одного слоя.
- Общее — спускать в `entities` или `shared`.
- Роутер: [`src/app/Router.tsx`](src/app/Router.tsx).

## Команды

```bash
npm --prefix frontend run dev       # :5180
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