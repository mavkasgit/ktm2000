# T-314 — Взятие в работу: показ источников, выбор оператором, предвыбор по `completed_operations`

Срез: `night/2026-10-03-314`. Тикет: [#314](https://github.com/mavkasgit/ktm2000/issues/314).

## Проверка фактов разведки чтением кода

| Факт из тикета | Проверка | Итог |
|---|---|---|
| `RemainderAllocationDialog.tsx` — read-only список, сортировка по количеству | файл, строки 78–105 (бывшие): `sort((a, b) => b.qty - a.qty)`, состояния выбора нет | подтверждено |
| фронт не передаёт `remainderAllocation` в `takeToWork` | `ExecutionPage.tsx:256, 718` — оба вызова без второго аргумента | подтверждено |
| бэкенд игнорирует `remainder_allocation` | `plan_generation.py:203-205`: «remainder_allocation игнорируется — нет legacy-таблицы» | подтверждено |
| порядок в `stock/api.py` — location→quality→ops | `list_balances_by_product` (ADR-0055 п.11) | подтверждено, но это **контракт ADR**, менять его нельзя |
| `transfers/budget.py` без ранжирования | файл — чистая арифметика остатков (`remaining_plain/transform/send`), подбора источников в нём нет | подтверждено, но ранжировать там нечего; файл не тронут |

## Правки прод-кода

### Backend

1. `backend/app/services/plan_generation.py`
   - `SourceIssue` + `resolve_source_issues()`: выбор оператора разрешается в
     строки `stock_balances` (товар/участок/качество/габарит/операции —
     пять осей ключа, ADR-0055) и в этап-получатель: **вход этапа**,
     совпадающий с признаком операций остатка (ADR-0055 п.7). Количество
     ограничивается остатком (`min`).
   - `release_batch()`: после создания заданий выдаёт выбранный остаток
     проводкой `TRANSFER_SEND` (`source_ref="take_to_work_source"`) на
     участок адресата; `task_id`/`transfer_id` не проставляются — остаток
     снят со склада до появления задания, иначе вырос бы «передано» в
     бюджете участка.
   - Отказы — `ValueError` с внятной причиной (не найден / чужой товар /
     пуст / операции не зафиксированы / признак не встречается на маршруте /
     динамический маршрут): `_process_position_take_to_work` превращает их в
     `status="failed"` с причиной.
   - Импорт `StockCommand/StockCommandService/Reason` поднят на модуль
     (был локальным внутри ветки автозавершения).
2. `backend/app/api/routes/production_planning.py`
   - `RemainderAllocationItem.remainder_id → balance_id` (legacy-имя ссылалось
     на удалённую `SpgRemainder`).
   - `remainder_allocation` при нескольких позициях — **422**, а не молчаливый
     дроп (дроп был реальной потерей выбора оператора).
3. `backend/app/stock/api.py`
   - `GET /stock/balance/by-product/{id}`: новый параметр `order`
     (`key` — по умолчанию, контракт ADR-0055 п.11; `operations` — порядок
     кандидатов выдачи, `jsonb_array_length(completed_operations) DESC`,
     `coalesce(...,0)` против `NULLS FIRST`, tie-break `location_id →
     quality_state → id`).

### Frontend

4. `frontend/src/shared/api/stock.ts`: `getProductStockBalances(..., order?)`,
   `completedOperationsCount()` (NULL = 0 — как на бэкенде).
5. `frontend/src/shared/api/productionPlans.ts`: `takeToWork` —
   `remainderAllocation: Array<{ balance_id; quantity }>`.
6. `RemainderAllocationDialog.tsx`: `SourceRow` (несёт `balanceId` и
   `opsCount`), сортировка по `opsCount` DESC → `location` → `quality` →
   `dims`, состояние выбора, предвыбор первой строки, запрос остатков с
   `order=operations`, передача выбора в `onConfirm(autoConsume, allocation)`,
   подпись выбранного источника под таблицей.
7. `ExecutionPage.tsx`: мутация `takeToWorkMutation` приняла
   `remainderAllocation`, `confirmLaunchWithAutoConsume` передаёт выбор.
8. `ExecutionDialogs.tsx`: в диалоге «Взять в работу» для массового режима
   сказано, почему источник там не выбирается.

## Тесты

`backend/tests/test_take_to_work_source_allocation.py` (10 тестов):
выдача на этап, чей вход совпадает с операциями остатка; prep-остаток идёт на
**следующий** этап; без выбора материал не двигается; потолок по остатку;
чужой товар; признак вне маршрута; `NULL`-группа; 422 на массовом запуске;
`order=operations` ставит prep выше сырья и не ломает `order=key`; `NULL`-ось
в `order=operations` уходит вниз.

`RemainderAllocationDialog.test.ts` (+4): порядок по операциям, а не по
количеству; детерминированность при равенстве; `NULL` = 0 операций; строка
несёт `balanceId`.

`RemainderAllocationDialog.ui.test.tsx` (3): предвыбор = максимум операций и
запрос с `order=operations`; клик по другому остатку уходит в `onConfirm`
выбранным; количество = `min(план, остаток)`.

## Не сделано (осознанно)

- **Автоподбор источника — #282**, не дублируется: здесь ручной выбор.
- **Массовое взятие в работу не принимает выбор источника.** Контракт
  `remainder_allocation` — одна позиция на запрос (у позиций разные маршруты и
  остатки); вместо молчаливого дропа теперь 422. Выбор источника в массовом
  режиме — отдельное продуктовое решение.
- `transfers/budget.py` не тронут: ранжирования источников в нём нет и по
  смыслу не должно быть (это арифметика передачи).
- ADR-0055 п.11 не переписан: `order=key` остался поведением по умолчанию,
  порядок кандидатов выдачи — отдельный явный параметр.

## e2e

Спека не добавлялась (DoD: полный `npm run test:e2e` не требуется). Прогон e2e
не выполнялся: слоты ночи заняты параллельными срезами.
