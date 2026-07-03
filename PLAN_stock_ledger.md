# План рефакторинга KTM-2000: SpgRemainder → Location-based Stock Ledger (fast/clean)

> Ветка: `refactor/stock-ledger`. Стратегия: big-bang по модулям, без сохранения
> обратной совместимости со старыми тестами/кодом. Старое просто выпиливается
> и заменяется, не адаптируется.

---

## Ключевое отличие от прошлой версии плана

- **Нет "baseline gate" на 4000 старых тестов.** Старые тесты на SpgRemainder/
  Movement, которые проверяют механику, уходящую в прошлое, — удаляются вместе
  с кодом, который они тестируют. Не чинить, не адаптировать, не жалеть.
- **Нет двойной записи (Movement + StockTransaction одновременно).** Каждая
  операция мигрирует одним прыжком: старая реализация вырезается, новая
  встаёт на её место в том же PR.
- **Тесты — новые, маленькие, по одной операции.** Не инвариантные простыни
  на тысячи строк, а короткие focused-тесты: дал команду → проверил баланс/
  запись/статус. 5-15 тестов на этап, не 30+.
- **Никакого "strangler", никаких adapter-слоёв, никакого legacy-режима.**
  Один путь записи (`StockCommandService`), один API (`/api/v2/stock/*`),
  старый API просто удаляется по мере готовности потребителей.

---

## Старт-протокол для новой сессии

1. Прочитать `AGENTS.md` и раздел «Прогресс» ниже — понять, на какой фазе.
2. `git branch --show-current` → должна быть `refactor/stock-ledger`.
3. Проверить миграции: alembic `current` ≥ `022_stock_ledger_core`.
4. Перед фазой — один explore-субагент (`north-mini-code-free`) на модуль,
   который трогаем. ТЗ: «Изучи [файлы] — верни список функций/вызовов,
   которые заменяются. Не пиши код.»
5. Выполнить фазу, коммит `feat(stock): Этап N — <что сделано>`, отметить
   `[x]` в «Прогресс».

Тесты пишет субагент (короткое ТЗ на 1 операцию), основной агент — модель/
сервисы/миграции/удаление старья.

---

## 0. Архитектурные принципы (не меняются)

1. Ядро хранит факты (StockTransaction), UI/сервисы — политики.
2. Баланс = projection из StockTransaction. Мутабельных остатков нет.
3. Append-only. Отмена = компенсационная транзакция.
4. Transfer — бизнес-обёртка над парой StockTransaction.
5. Спорная механика (автопотребление, переделка, quality) — явная команда +
   запись в журнале, видимая в UI.

## 1. Целевая модель (без изменений по сути)

- **Location** = `sections` + `type: LocationType` enum.
- **StockTransaction**: `product_id, from_location_id, to_location_id, quantity,
  reason, from_quality_state, to_quality_state, task_id, transfer_id,
  idempotency_key, ...`
- **StockBalance**: projection по `(product, location, quality_state)`.
- **WorkTask**: `completed_qty/scrap_qty` — мутабельный агрегат, обновляется
  проекцией.
- **StockCommandService.record(cmd)** — единственный путь записи, внутри
  синхронно дергает `StockProjectionManager`.

Reason enum и QualityState enum — как в предыдущей версии, без изменений.

---

## 2. Этапы (сжато, без страховки на старых тестах)

### Этап 0 — Подготовка (готово)
- [x] Ветка, AGENTS.md, черновики инвариант-тестов

### Этап 1 — Ядро (готово)
- [x] Модели, миграция `022_stock_ledger_core`, `StockCommandService`,
  `ProjectionManager`
- [x] ~10 коротких тестов: record → баланс меняется, идемпотентность,
  negative balance запрещён

### Этап 2 — Transfer (переписать напрямую, без двойной записи)
- [x] 2.1. `transfer_send` — вырезать запись в `Movement`, писать только
  2× `StockTransaction` (SEND/RECEIVE)
- [x] 2.2. `cancel_transfer`/`correct_transfer` — компенсационные
  StockTransaction вместо правки Movement
- [x] 2.3. `/api/v2/stock/balance`, `/api/v2/stock/transactions`
- [x] 2.4. Старые тесты transfer'ов на Movement — удалить, написать 5-8
  новых коротких (send/cancel/correct/partial → баланс верный)

### Этап 3 — Shopfloor (каскад схлопывается сразу, целиком)
- [ ] 3.1. `issue_to_work` → `record(ISSUE_TO_WORK, auto_consume=bool)`
- [ ] 3.2. `complete_task` → `record(COMPLETE)` [+ `record(SCRAP)` при браке]
- [ ] 3.3. Удалить одним махом: `return_remainder_to_stock`,
  `compensate_spg_remainders`, `trigger_auto_consume_for_spg_tasks`,
  `auto_consume_available_remainders`, `consume_remainder`. Заменить на
  один вызов `record(RETURN_TO_STOCK)` / `issue_to_work(auto_consume=True)`
- [ ] 3.4. Их старые тесты — удалить вместе с кодом, не адаптировать.
  Написать 8-10 новых: по одному на каждую новую команду

### Этап 4 — WorkTask cleanup
- [ ] 4.1. `_refresh_task_cache` → читает из StockBalance/transactions
- [ ] 4.2. `cached_*` колонки — удалить сразу (не через отдельную миграцию
  "потом"), если фронт на этот момент готов (см. Этап 6)
- [ ] 4.3. 3-4 теста: `completed_qty` считается верно из ledger

### Этап 5 — Quality
- [ ] 5.1. Data-migration: `quality_state=GOOD` для старых транзакций
- [ ] 5.2. `Defect.stock_transaction_id` FK
- [ ] 5.3. `DefectDecision` → `record(...)` по таблице reason (см. старую
  версию плана, раздел не менялся)
- [ ] 5.4. 5-6 тестов по веткам решений (scrap/rework/return/hold)

### Этап 6 — Frontend (тоже big-bang, не strangler)
- [ ] 6.1. `shared/api/stock.ts`
- [ ] 6.2-6.4. Заменить компоненты на новый API напрямую (не городить
  переключатель legacy/new)
- [ ] 6.5. UI для явных команд: чекбокс автопотребления, кнопки
  scrap/rework, индикатор перевыполнения
- [ ] 6.6. Убрать `SpgRemainder` с фронта полностью

### Этап 7 — Cleanup
- [ ] 7.1. Удалить `SpgRemainder` (модель, таблица)
- [ ] 7.2. Удалить `Movement` (модель, таблица)
- [ ] 7.3. Удалить старые `_make_*` хелперы и всё, что осталось
- [ ] 7.4. Обновить `AGENTS.md`

---

## 3. Тестирование — коротко и по делу

- Тестируем **новое поведение**, а не совместимость со старым.
- 1 операция = 3-6 тестов (happy path, edge case, идемпотентность/ошибка).
- Инвариант оставляем один, реально ценный:
  `stock_balance = SUM(stock_transactions)` по `(product, location, quality_state)`.
  Остальные "парные" сверки с Movement — не нужны, т.к. двойной записи нет.
- Старые тесты, привязанные к удаляемому коду, — удаляются в том же PR, где
  удаляется код. Не переносим их в TODO, не оставляем skip-помеченными.

---

## 4. Риски и откат

| Риск | Митигация |
|---|---|
| Откат сложнее без двойной записи | Бэкап БД перед этапами 2, 3, 5, 7; git revert по этапам |
| Фронт временно рассинхронизирован с бэком в рамках этапа | Этапы 2-5 мержить в ветку целиком, не в main поэтапно, пока фронт (Этап 6) не готов |
| Потеря покрытия там, где старые тесты не заменили новыми | Явный чек-лист "что удалили → что написали взамен" в коммите |

Точка невозврата — Этап 7, как и раньше.

---

## 5. Прогресс

- [x] Этап 0 — Подготовка
- [x] Этап 1 — Ядро inventory
- [x] Этап 2 — Transfer
- [ ] Этап 3 — Shopfloor
- [ ] Этап 4 — WorkTask cleanup
- [ ] Этап 5 — Quality
- [ ] Этап 6 — Frontend
- [ ] Этап 7 — Cleanup