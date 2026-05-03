# Routing Rules for Anodized Aluminum Profile Production

## Default Route Formula

Factoryflow uses one common route shape. Product routes are reduced versions of this route: omitted operations are not stored as fake steps.

```text
WH
→ [DRILL | PRESS_WINDOW | PRESS_COMB | NONE]
→ [SHOT | NONE]
→ ANOD
→ [
    FG_WH
    |
    WIP_WH → SAW → PACK → FG_WH
  ]
```

## Sections

Sections describe physical control points, not every technological operation.

| Code | Name | Kind |
| --- | --- | --- |
| WH | Склад сырья | raw_stock |
| DRILL | Сверловка | production |
| PRESS | Пресс | production |
| SHOT | Дробеструйная обработка | production |
| ANOD | Анодирование | production |
| WIP_WH | Склад полуфабриката | wip_stock |
| SAW | Пила | production |
| PACK | Упаковка | production |
| FG_WH | Склад готовой продукции | finished_stock |

## Operations

`PRESS_WINDOW` and `PRESS_COMB` are operation codes on the `PRESS` section. They are not separate sections.

| Operation Code | Section | Meaning |
| --- | --- | --- |
| ISSUE_RAW | WH | Выдача сырья |
| DRILL | DRILL | Сверловка |
| PRESS_WINDOW | PRESS | Пресс окно |
| PRESS_COMB | PRESS | Пресс гребенка |
| SHOT | SHOT | Дробеструйная обработка |
| ANOD | ANOD | Анодирование |
| MOVE_TO_WIP | WIP_WH | Передача на склад полуфабриката |
| SAW | SAW | Пила |
| PACK | PACK | Упаковка |
| PACK_GLUE | PACK | Упаковка с клеевой операцией |
| PACK_DIFFUSER | PACK | Упаковка с рассеивателем |
| ACCEPT_FINISHED | FG_WH | Приемка готовой продукции |

## Design Decisions

- Skipped operations are represented by missing `route_steps`, not by `NONE` or `SKIP` sections.
- `SHOT` is included by default in templates, but can be omitted per product route.
- `WH`, `WIP_WH`, and `FG_WH` are route steps in MVP because they are physical control points for movements.
- Stock sections have `kind != production`; this lets the UI and future execution logic distinguish stock control from production work.
- Дополнительные операции `PACK_GLUE` и `PACK_DIFFUSER` выполняются на участке `PACK` и не создают отдельные участки маршрута.
- A route should normally start with `WH` and end with `FG_WH`, but this is a recommendation until route validation is hardened.

## Examples

Full route through semifinished stock:

```text
WH / ISSUE_RAW
→ PRESS / PRESS_WINDOW
→ SHOT / SHOT
→ ANOD / ANOD
→ WIP_WH / MOVE_TO_WIP
→ SAW / SAW
→ PACK / PACK
→ FG_WH / ACCEPT_FINISHED
```

Short route after anodizing directly to finished stock:

```text
WH / ISSUE_RAW
→ PRESS / PRESS_COMB
→ SHOT / SHOT
→ ANOD / ANOD
→ FG_WH / ACCEPT_FINISHED
```

Route without primary operation:

```text
WH / ISSUE_RAW
→ SHOT / SHOT
→ ANOD / ANOD
→ FG_WH / ACCEPT_FINISHED
```
