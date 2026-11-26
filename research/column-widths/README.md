# Research: ширины колонок таблиц

Исследовательский стенд для спеки
[`docs/specs/preview-column-widths.md`](../../docs/specs/preview-column-widths.md)
(эпик [#475](https://github.com/mavkasgit/ktm2000/issues/475)).

Здесь нет продуктового кода: только синтетика, измерители, оптимизаторы и бенч.
Результат исследования — решение, какой алгоритм и какие константы брать в
`ImportRemaindersDialog`.

## Состав

| Файл | Что делает |
|---|---|
| `lib/prng.mjs` | seeded PRNG (mulberry32) — прогон воспроизводим |
| `lib/generator.mjs` | 7 профилей синтетических листов: `realistic`, `long-tail`, `outlier`, `all-short`, `mono`, `mixed`, `empty` |
| `lib/text.mjs` | табличные метрики 11px, жадный перенос, clamp, ширина пилюль |
| `lib/offscreen-canvas.mjs` | `OffscreenCanvas`-полифилл для Node (контракт Canvas 2D, который читает pretext) |
| `lib/measurers.mjs` | `greedy`, `ceil`, `pretext` (в Node — через подставленный `OffscreenCanvas`) |
| `lib/columns.mjs` | модель колонок предпросмотра, минимумы, текущие доли |
| `lib/evaluate.mjs` | подготовка листа и оценка высоты/обрезки |
| `lib/optimizers.mjs` | `baseline`, `auto`, `p90`, `narrowing`, `breakpoints`, `oracle` |
| `bench.mjs` | матрица, JSON и markdown-отчёт |
| `browser/` | Playwright-стенд H4: `pretext` против реального DOM (`table-fixed`, те же шрифты и ширины); [README](./browser/README.md) |
| `test/` | unit-тесты на детерминизм, границы профилей, перенос, контракт измерителей, инварианты оптимизаторов |

## Профили и калибровка

`lib/generator.mjs` строит лист по seed: один и тот же seed даёт одинаковые
данные, разные профили — разные стресс-условия. Измеренные перцентили длин
лежат в `CALIBRATION`, тесты сверяются с ними, а не с точной
последовательностью PRNG.

| Профиль | Что моделирует | Границы |
|---|---|---|
| `realistic` | обычный ОСВ | наименования p50/p90/p99 ≈ 12/23/45 (измерено 12/25,5/46,8), артикулы 7/8/12, ошибки p50/p90/p99 ≈ 33/53/73 |
| `long-tail` | тяжёлый хвост наименований, p50/p90/p99 ≈ 3× реалистичных | стресс, а не калибровка |
| `outlier` | ровно один выброс на текстовую колонку и одна строка с 6 пилюлями | `OUTLIER_TEXT_MIN_LENGTH = 100`, `OUTLIER_PILL_COUNT = 6` |
| `all-short` | короткие наименования и ошибки | всё ≤ `ALL_SHORT_MAX_LENGTH = 25` |
| `mono` | длинные артикулы без пробелов | 12–16 символов, без whitespace |
| `mixed` | латиница и кириллица в одном листе | наименования около реалистичных |
| `empty` | пустые значения и пустые пилюли | ~30 % пустых строк, ~20 % пустых `operations` |

Источник калибровки — выборка без персональных данных:
`docs/catalog/ktm-profile-register.csv` (216 наименований и артикулов
прод-каталога, снимок 2026-11-26) и тексты ошибок предпросмотра из
`backend/app/stock/import_service.py` / `import_1c_osv.py` (14 сообщений).
Перцентили ошибок считаются только по непустым ячейкам: пустая ячейка
встречается чаще ошибки и о длине текста ничего не говорит.

5000 строк на 12 колонках генерируются примерно за 15–20 мс; тест держит
потолок 1 с и 128 МБ на лист.

## Как добавить профиль

1. Добавить имя в `PROFILES` (`lib/generator.mjs`) — тест на число профилей и
   цикл детерминизма подхватят его автоматически.
2. Задать правило в `makeValue` / `makeError` / `makePills`: профиль должен
   отличаться от `realistic` измеримым признаком, а не только seed'ом.
3. Если признак — граница (длина, число пилюль), вынести её в экспортируемую
   константу рядом с `ALL_SHORT_MAX_LENGTH` и проверять в тесте той же
   константой, без дублирования литерала.
4. Добавить в `test/generator.test.mjs` проверку признака и отличия от
   соседних профилей; обновить таблицу выше.
5. `npm test --prefix research/column-widths` — и при желании
   `node research/column-widths/bench.mjs --quick`.

## Запуск

```bash
npm install --prefix research/column-widths   # @chenglou/pretext, vite, @playwright/test
node research/column-widths/bench.mjs --quick # 2 профиля, быстрый прогон
node research/column-widths/bench.mjs         # полная матрица
npm test --prefix research/column-widths
npm --prefix research/column-widths run browser:test  # H4: pretext против DOM
```

Результаты пишутся в `results/bench.json` и `results/report.md`; каталог
`results/` не коммитится — итоговый отчёт исследования живёт в `docs/research/`.

## Измерители

У всех трёх реализаций один интерфейс, поэтому оптимизатор не знает, каким
движком считается строка:

```js
const prepared = measurer.prepare(text, font); // font: "sans" | "mono"
measurer.naturalWidth(prepared);               // ширина в одну строку
measurer.maxWordWidth(prepared);               // самый широкий неразрывный кусок
measurer.lineCount(prepared, usableWidth);     // число строк при ширине
```

| Измеритель | `role` | Модель |
|---|---|---|
| `greedy` | `primary`, дефолт бенча | табличные метрики 11px + жадный перенос по пробелам (`overflow-wrap: normal`) |
| `ceil` | `baseline` | линейное `ceil(naturalWidth / usable)`, только точка отсчёта в отчёте |
| `pretext` | `primary` | `@chenglou/pretext`: `prepareWithSegments` + `measureLineStats` + `measureNaturalWidth`; перенос по правилам браузера, включая дефис |

`ceil` не попадает в финальное решение: `--measurer` по умолчанию `greedy`, а
`role: "baseline"` помечает его явно (тест `ceil помечен baseline и не
является дефолтом`).

**Шрифты.** Строка canvas-шрифта строится только через `cssFont()`:
`11px "Inter"` (`sans`) и `11px "JetBrains Mono"` (`mono`). Это те же семейства
и размер, что в CSS предпросмотра (`text-[11px]`); менять размер нужно в
`FONT_PX`, иначе модель и DOM разойдутся.

**Node без DOM.** pretext на этапе `prepare()` требует Canvas 2D:
`new OffscreenCanvas(1, 1).getContext("2d")`, `context.font`, `context.measureText`.
`lib/offscreen-canvas.mjs` ставит в `globalThis` минимальный полифилл с этим
контрактом:

- `getContext("2d")` возвращает один и тот же контекст на канвас;
- `context.font` — строковое свойство, читается обратно (pretext так проверяет,
  что контекст принял шрифт);
- `context.measureText(text).width` — ширина из таблицы 11px (`text.mjs`);
- `context.letterSpacing` намеренно отсутствует — pretext видит, что контекст
  не умеет letter-spacing, и не идёт по ветке letter-spaced shaping.

**Согласие с greedy.** На тексте без дефисов и при ширине не уже самого
длинного слова `pretext` и `greedy` дают одинаковое число строк (тест
`pretext и greedy согласны на синтетике без переносов по дефису`). Где модели
расходятся, это записано отдельно:

- pretext переносит после дефиса/soft hyphen (как браузер), greedy — нет:
  `maxWordWidth` у pretext считается по сегментам и на `AL-6060` меньше, а
  строк при узкой колонке — меньше (тест `граница модели: pretext переносит по
  дефису, greedy — нет`);
- при ширине уже самого длинного слова pretext делает аварийный перенос внутри
  слова (`overflow-wrap: break-word`), greedy оставляет слово в одной
  переполненной строке.

## Браузерная валидация (H4)

Стенд [`browser/`](./browser/README.md) меряет те же строки дважды: `pretext`
и реальный Chromium в `table-fixed`-ячейке с `line-height: 20px` из
`columns.mjs` и `overflow-wrap: normal`. Профили — все семь, текстовые
колонки — `source_name` и `errors`, ширины контента 90–280 px (продуктовый
диапазон), seed 1, 100 строк.

```bash
npm install --prefix research/column-widths
npm --prefix research/column-widths run browser:test
```

Текущий вердикт (2026-11-26, Chromium 1254): **H4 достигнут** — 9
расхождений на 4656 непустых ячеек (**0.19%**) по строкам и по высоте.
Все 9 — `errors` на ширине 90 px, где слово «поддерживается» шире контента
на 0.84 px: `pretext` рвёт его как `overflow-wrap: break-word`, а CSS с
`normal` оставляет в одной строке. Там, где `usableWidth >= maxWordWidth`,
расхождений **0** (4647 ячеек), включая дефисные артикулы; mono-диагностика —
0 из 6730. Вывод для модели: `pretext` точен, но оптимизатор обязан держать
`w_i >= CELL_PADDING_PX + maxWordWidth` (или CSS должен быть `break-word`).
Сырой JSON — `results/browser.json` (не коммитится), таблицы и разбор причин —
в [`browser/README.md`](./browser/README.md).

## Границы модели

- В Node текст измеряется табличными метриками, а не canvas: сравнивать
  раскладки между собой можно, абсолютные пиксели — только после валидации
  в браузере (отдельный тикет). В браузере тот же `pretext`-адаптер меряет
  настоящим canvas, полифилл не нужен.
- **`letter-spacing`** не моделируется: таблица 11px его не знает, полифилл не
  выставляет `context.letterSpacing`, `greedy`/`ceil` его игнорируют. Если в CSS
  предпросмотра появится `letter-spacing`, его нужно передать в
  `prepare(..., { letterSpacing })` и пересчитать модель — иначе число строк
  занижено.
- **`line-height`** в модель не входит: измеритель возвращает число строк,
  высоту строки задаёт `LINE_HEIGHT_PX` в `columns.mjs`. `line-clamp` — это
  потолок строк у потребителя (`clamp` в `columns.mjs`), а не свойство текста.
- **`overflow-wrap`** у моделей разный: `greedy` — `normal` (длинное слово не
  рвётся), `pretext` — `break-word` (рвётся). Для колонки с
  `overflow-wrap: normal` в CSS `maxWordWidth` — нижняя граница ширины, ниже
  которой `pretext` начнёт делить слово и покажет больше строк, чем браузер.
- **Именованный шрифт.** Модель знает только `sans`/`mono`; canvas-строка
  (`11px "Inter"` / `11px "JetBrains Mono"`) важна для браузера, где pretext
  меряет реальный шрифт. Подмена семейства в CSS без правки `FONT_FAMILY`
  делает браузерные числа невалидными.
- **Загрузка веб-шрифта.** В браузере `prepare()` до `document.fonts.ready`
  (или без `font-display`) меряет fallback-шрифт: строки будут другими, хотя
  код не менялся. Синтетика в Node от этого не зависит, поэтому расхождение
  проявляется только на DOM-валидации.
- `Операции` смоделированы как неразрывные пилюли: ширина покупает отсутствие
  обрезки, а не число строк.
- `oracle` перебирает пороги только гибких колонок и только на малых
  инстансах; он эталон для `cost`, а не для продакшена.
