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
| `lib/measurers.mjs` | `greedy`, `ceil`, `pretext` (в Node — через подменённый `OffscreenCanvas`) |
| `lib/columns.mjs` | модель колонок предпросмотра, минимумы, текущие доли |
| `lib/evaluate.mjs` | подготовка листа и оценка высоты/обрезки |
| `lib/optimizers.mjs` | `baseline`, `auto`, `p90`, `narrowing`, `breakpoints`, `oracle` |
| `bench.mjs` | матрица, JSON и markdown-отчёт |
| `test/` | unit-тесты на детерминизм, перенос, инварианты оптимизаторов |

## Запуск

```bash
npm install --prefix research/column-widths   # @chenglou/pretext
node research/column-widths/bench.mjs --quick # 2 профиля, быстрый прогон
node research/column-widths/bench.mjs         # полная матрица
npm test --prefix research/column-widths
```

Результаты пишутся в `results/bench.json` и `results/report.md`; каталог
`results/` не коммитится — итоговый отчёт исследования живёт в `docs/research/`.

## Границы модели

- В Node текст измеряется табличными метриками, а не canvas: сравнивать
  раскладки между собой можно, абсолютные пиксели — только после валидации
  в браузере (отдельный тикет).
- `Операции` смоделированы как неразрывные пилюли: ширина покупает отсутствие
  обрезки, а не число строк.
- `oracle` перебирает пороги только гибких колонок и только на малых
  инстансах; он эталон для `cost`, а не для продакшена.
