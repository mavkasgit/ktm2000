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
| `test/` | unit-тесты на детерминизм, перенос, инварианты оптимизаторов, контракт измерителей |

## Запуск

```bash
npm install --prefix research/column-widths   # @chenglou/pretext
node research/column-widths/bench.mjs --quick # 2 профиля, быстрый прогон
node research/column-widths/bench.mjs         # полная матрица
npm test --prefix research/column-widths
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
