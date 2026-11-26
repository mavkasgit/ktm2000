# Разделы и загрузка кода — обоснования

Правила — в [`frontend/AGENTS.md`](../../frontend/AGENTS.md), раздел «Разделы и
загрузка кода». Здесь история, замеры и механика.

**Когда читать:** при правке `src/app/Router.tsx`, `src/app/lazyRoute.tsx`,
`src/app/Layout.tsx`, `src/app/main.tsx`; при добавлении раздела или маршрута;
при изменении порога в [`bundle-size-baseline.json`](../../frontend/bundle-size-baseline.json)
или разборе падения шага гейта `frontend-build`.

- Страница раздела подключается **только** через `lazyPage`
  ([`src/app/lazyRoute.tsx`](../../frontend/src/app/lazyRoute.tsx)). Статический импорт
  страницы в [`src/app/Router.tsx`](../../frontend/src/app/Router.tsx) возвращает все
  разделы в начальный пакет: до #199 он весил 2 538 КБ (653 КБ gzip), а
  порог держит шаг гейта `frontend-build` — замер 2026-11-18: 1 827 КБ
  (511 КБ gzip) при пороге в
  [`bundle-size-baseline.json`](../../frontend/bundle-size-baseline.json) с допуском 1%.
  Начальный пакет — это `<script src>` + `modulepreload` + `stylesheet` из
  `dist/index.html`; ленивые чанки разделов в него не входят.
- Ссылка на модуль страницы — **по файлу страницы**
  (`import("../features/references/pages/ProductsPage")`). Барелы
  `features/references`, `features/planning` и `features/admin` удалены
  вместе с переходом на ленивую загрузку: импортировать страницу из барела
  больше нечего, а `tsc` не даёт вернуть путь, которым начальный пакет снова
  становится 2,5 МБ.
- Граница `Suspense` живёт один раз — на `<Outlet />` в
  [`src/app/Layout.tsx`](../../frontend/src/app/Layout.tsx) и на маршрутах вне каркаса
  (`/login`, `/auth/callback`). Своя граница на странице — нельзя: её легко
  забыть, и тогда переход в этот раздел покажет белый экран.
- Пока едет чанк, видно `RoutePending`, а не пустое место. Обзор
  (`DashboardPage`) остаётся в начальном пакете: это первый экран, и ждать
  его чанк после каркаса — значит показать спиннер там, где его не было.
- Флаг `future={{ v7_startTransition: true }}` у `RouterProvider`
  ([`src/app/main.tsx`](../../frontend/src/app/main.tsx)) нельзя снимать: без него переход
  в ещё не загруженный раздел — синхронное обновление, React прячет прежний
  раздел вместе с фокусом и рисует фолбэк вместо него.
- Термин и правило — [ADR-0039](../adr/0039-stranica-razdela-prishodit-svoim-chankom.md)
  и [`GLOSSARY.md`](../../GLOSSARY.md).
