# T-300 — авто-передачи: замер не доведён, кода не тронуто

**Тикет:** #300 · **Ветка:** `night/2026-10-02-a` · **Состояние: разбор сделан, правки нет.**

## Что в коде (подтверждено чтением `app/transfers/services.py:883-975`)

Цикл `auto_create_transfer_after_complete` на КАЖДЫЙ шаг цепочки читает:

| читает | запросов на шаг |
|---|---|
| `db.get(SectionPlanLine, current_task.section_plan_line_id)` | 1 |
| следующая строка плана (по позиции и `sequence + 1`) | 1 |
| `db.get(RouteStage, current_line.route_stage_id)` | 1 |
| `sections_share_spg(current, next)` | 2 |
| `db.get(RouteStage, next_line.route_stage_id)` | 1 |
| задача следующего этапа | 1 на транзитном, **иначе по одной на пару** (`dimensions_match_clause`) |

То есть ~6 на шаг и ×`len(pairs)` на последнем шаге — O(steps × pairs),
как и написано в тикете. Батчить есть что.

Нужен замер «до», а он требует фикстуры, которой в тестах нет. Попытка
собрать её на готовых хелперах упёрлась в устройство ledger'а:

* `complete_task` требует выпуска материала на участок задачи — иначе
  `ValueError: Complete quantity exceeds issued quantity`;
* `Reason.ISSUE_TO_WORK` в ledger **запрещён** (`StockValidationError:
  reason=issue_to_work is no longer allowed; use TRANSFER_SEND/TRANSFER_RECEIVE`),
  то есть правильный выпуск — это `MANUAL_IN` на склад сырья плюс
  `transfer_send`/`transfer_receive` на участок;
* а эта передача сама является write-путём и сама меняет счётчик, который
  и предстоялось мерить.

Значит фикстура цепочки «3 участка в разных СПГ + 2 пары» требует ещё и
собственной передачи для выпуска — то есть инфраструктуры того же класса, что
пункт 5 из #299 (клон-БД, #304). Без неё я получил бы «замер» на пустой
выдаче и выдал бы его за результат.

**Правило, которым я себя связал:** на этом тикете ответ «быстрее» без
замера и без зелёного `assert_no_invariants_violations` — это не результат.
Поэтому кода не тронуто.

## Что нужно, чтобы закрыть тикет

1. Клон-БД dev-данных (механика #304) **или** готовая фикстура цепочки из
   `tests/stock/`: склад сырья + выпуск `MANUAL_IN` + `transfer_send` на
   участок, затем `complete_task` на первом этапе.
2. Замер «до» на этой фикстуре: SQL по глаголам при 2–3 шагах и 2 парах.
3. Правка: строки плана позиции одним `IN`, этапы по id одним `IN`, СПГ всех
   участков одним `select(SpgSection.section_id, spg_id)`, открытые задачи всех
   строк одним `select(WorkTask)` с сопоставлением габаритов в Python по
   тому же правилу, что `dimensions_match_clause` (`None` — это SQL NULL и
   JSON `null`).
4. После правки — тот же замер плюс `assert_no_invariants_violations`,
   `stock/test_transfer_ledger`, `test_transfer_budget_consistency`,
   `test_transferable_module`, `test_transfer_dimensions`.

## Границы

`route_builder.py` / `route_selection.py` не трогались. Миграций нет.
Формулы `transfer_send` и побочные эффекты цепочки не тронуты — семантику
передач менять не предполагалось.
