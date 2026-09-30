# T-0011 — Тест «релиз без маршрута» проходил при любом поведении

- **Категория:** проверка самих тестов (тесты, которые не могут упасть)
- **Статус:** DONE (коммит см. `JOURNAL.md`)
- **Дата:** 2026-10-01, цикл 3
- **Файл (не в denylist):** `backend/tests/test_take_to_work_e2e.py`

## Проблема и доказательство

`test_take_position_to_work_fails_without_route` (имя: «позиция без маршрута не
уходит в работу») состоял из try/except с печатью:

```python
try:
    batch_result = await create_release_batch(...)
    print(f"⚠️  Release batch created without route_id: {batch_result}")
except Exception as e:
    print(f"✅ Release correctly failed without route_id: {type(e).__name__}")
```

Ни одного `assert`: тест проходил и когда релиз корректно отказывал, и когда
релиз молча создавался (это лишь печаталось «⚠️»). Плюс сетап был слабее
проверяемого контракта: позиция создавалась в статусе `draft`, а
`create_release_batch` требует утверждённых плана и позиции — то есть отказ
мог прийти раньше проверки маршрута, и тест проверял не то, что заявляет.

Проверено прогоном (`logs/T-0011-probe.log`, serial, scratch-DB): реальное
поведение — `ValueError` из `app/services/plan_generation.py:95`
(`"Position {id} has no route assigned - cannot release without route"`).

## План изменений

1. Сетап доведён до состояния «готова к релизу»: `ProductionPlanStatus.approved`
   у плана и `PlanPositionStatus.approved` у позиции — тогда единственная
   причина отказа именно отсутствие `route_id`.
2. try/except заменён на утверждение контракта:
   ```python
   with pytest.raises(ValueError, match="has no route assigned"):
       await create_release_batch(...)
   ```
3. Убраны отладочные `print("✅ …")` из обоих тестов файла (они не несут
   информации в отчёте и создавали шум при `-s`); утверждения не тронуты.

## Граница: что НЕ затронуто

- Продуктовый код — не менялся; утверждение описывает фактическое поведение
  (`ValueError` с конкретным текстом), зафиксированное прогоном.
- Ассерты в первом тесте файла (`test_take_position_to_work_with_dynamic_route`)
  не менялись — удалены только печати.
- Ни один тест не удалён и не скипнут.

## Критерии готовности (измеримые)

1. `tests/test_take_to_work_e2e.py`: `2 passed` (до и после).
2. Новое утверждение проходит — контракт «релиз без маршрута → ValueError»
   подтверждён; если бы не проходило, это продуктовый дефект → отдельный тикет.
3. Полный прогон: `1945 passed, 0 failed, 43 warnings` (число тестов не
   изменилось).
4. Диффа — один файл.

## План отката

`git revert <commit>`.

## Артефакты

- `logs/T-0011-probe.log` — serial-прогон с печатями (до правки),
- `logs/T-0011-targeted.log` — после правки.
