# T-307 — авто-передачи: батчинг окупается на длинной цепочке

**Тикет:** #307 (остаток #300) · **Ветка:** worktree #307 · **Состояние: батчинг применён.**

## Кейс

`backend/tests/test_auto_transfer_batch_300.py`, фикстура `_prepare_long_chain`:

```
RAW → P1 → W1 → W2 → P2
```

* `P1` — производственный участок (СПГ по умолчанию), материал на него заведён
  приёмом `TRANSFER_RECEIVE` — иначе `complete_task` упадёт на `issued_quantity`;
* `W1`, `W2` — **транзитные** этапы (`stage_kind='transit'`,
  `storage_section_id` на `wip_stock`), каждый в своём СПГ;
* `P2` — производственный финальный этап в четвёртом СПГ; его задание ждёт
  материал (`waiting_previous`).

Три перехода `P1 → W1 → W2 → P2`, из них два — транзитные хопы. Длиннее
цепочку в текущем коде не сделать: `auto_create_transfer_after_complete`
продолжается только через `next_stage.is_transit`, после первого
производственного шага — `break`. Вариант 2 из тикета (несколько пар выходов)
не понадобился: длинная цепочка дешевле по фикстуре и разворачивает цикл
именно по шагам.

Замер — слушатель `before_cursor_execute` на engine, `transfer_send`
обёрнут вложенным счётчиком (`_measure_completion` в тест-файле), транзакция
теста откатывается фикстурой `session`. Счётчик сбрасывается перед
`complete_task`. Ответ и все три передачи сверены до/после.

## Числа (Windows, Postgres :5441, `-n 0`, один прогон; время — вторично)

| | до | после | Δ |
|---|---|---|---|
| `complete_task` всего | **224** | **209** | −15 (−6.7%) |
| — SELECT | 177 | 162 | −15 |
| — INSERT / UPDATE / DELETE | 24 / 19 / 4 | 24 / 19 / 4 | 0 |
| цикл `auto_create_transfer_after_complete` без `transfer_send` | **23** | **8** | −15 (−65%) |
| — SELECT в цикле | **22** | **7** | −15 |
| `transfer_send` × 3 | 156 | 156 | 0 |
| время `complete_task`, мс (один прогон) | 449 | 326–466 | шум, вторично |

Ответ идентичен: `task_id=17`, `status=completed`, `completed_quantity=100`,
`transaction_ids` — 2. Передачи идентичны: `P1→W1→W2→P2`, по 100 шт,
`dimensions=None`, `accepted`, у каждой пара проводок
`TRANSFER_SEND`/`TRANSFER_RECEIVE`. Инварианты ledger'а зелёные.

Семь SELECT'ов цикла после правки: строки позиции (1), этапы (1) + selectin
операций этапов (1), СПГ всех секций (1), открытые задачи всех строк (1) и
два `db.get` задач, созданных самими передачами (identity map держит их
слабой ссылкой — те же два запроса были и до правки). Число не зависит от
длины цепочки; до правки было ~7 SELECT'ов **на шаг**.

## Цена на короткой цепочке (#300)

| | до | после |
|---|---|---|
| `complete_task` всего | 96 | **97** |
| цикл (SELECT / всё) | 4 / 5 | 5 / 6 |
| `transfer_send` × 1 | 48 | 48 |

Один шаг и одна пара: поштучные `db.get` попадали в identity map и стоили
ноль, снимок добавил свой запрос. Это ровно результат #300 (96 → 97) и
осознанная цена: фиксированный проход окупается с третьего перехода.
Порог зафиксирован в бюджетном тесте: цикл на трёх переходах — не больше
8 SELECT'ов (до правки — 22; на старом коде тест падает).

## Что применено (строго по ТЗ T-300)

* строки позиции — один `select(SectionPlanLine)` по `plan_position_id`;
* этапы по id — один `IN`;
* членство секций в СПГ — один `select(SpgSection.section_id, spg_id)` на все
  секции цепочки;
* открытые задачи всех строк — один `select(WorkTask)` с
  `status NOT IN (closed)`; сопоставление габаритов — в Python
  (`_dimensions_equal`), `None` матчит и SQL `NULL`, и JSON `null` так же,
  как `dimensions_match_clause`.

`transfer_send`, формулы бюджета, побочные эффекты цепочки и миграции не
тронуты. Задачи, созданные передачами внутри цикла, добавляются в снимок
строки — следующая пара/шаг видит их так же, как увидел бы точечный SELECT.

## Тесты

```
npm run test:pytest -- tests/test_auto_transfer_batch_300.py \
  tests/stock/test_transfer_ledger.py tests/stock/test_complete_task_status_sync.py \
  tests/test_transfer_budget_consistency.py tests/test_transferable_module.py \
  tests/test_transfer_dimensions.py tests/transfers/test_budget.py \
  tests/test_transfers_ready.py tests/test_transfers_ready_lazy_task.py \
  tests/test_stock_to_production_transfer.py tests/test_stock_to_stock_transfer_ready.py
```

94 passed. E2E не запускался (изменён только write-хелпер и тесты).
