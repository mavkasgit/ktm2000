# Backend Tests (pytest)

Каноническое руководство по pytest в KTM-2000. Стек: **pytest**, **pytest-xdist**, **pytest-testmon**.

## Изоляция базы данных (hybrid mode)

Режим: `PYTEST_DB_MODE=hybrid` (единственный поддерживаемый).

1. **Временная БД на модуль** (`scope="module"`): `ktm_test_<module>_<runid>` — создаётся и удаляется вокруг каждого тестового модуля.
2. **Схема на модуль**: одна схема `t_<uuid8>` на модуль, `Base.metadata.create_all()` при старте модуля.
3. **Транзакция на тест** (`function scope`): каждый тест в SAVEPOINT; по завершении — `rollback`.
4. **Сброс sequence users**: перед каждым тестом `ALTER TABLE users ALTER COLUMN id RESTART WITH 1` — `system_user` всегда `id = 1`.

Подробности реализации: [`conftest.py`](conftest.py).

## Правила написания тестов

- **Динамические ID** — не полагайтесь на `id = 1, 2, 3`; читайте `product.id`, `task.id` из объекта.
- **Изоляция транзакций** — `session.commit()` в тесте фиксирует только savepoint, не основную транзакцию.
- **Не мутируйте module-scope данные** — общие фикстуры `scope="module"` только для чтения.
- **Integrity helper** — после Transfer/StockTransaction:
  ```python
  from tests.test_integrity_invariants import assert_no_invariants_violations
  await assert_no_invariants_violations(session, context="your-context")
  ```

## Команды (из корня проекта)

| Команда | Назначение |
|---------|------------|
| `npm run test:pytest:fast` | Параллельный прогон (рекомендуется, ~3 мин) |
| `npm run test:pytest:mon` | Только изменённые тесты (testmon) |
| `npm run test:pytest:lf` | Только упавшие в прошлый раз |
| `npm run test:pytest` | Полный прогон в один поток |

Отладка вручную:

```bash
npm run test:db:up && npm run test:db:wait
cd backend
pytest -v -k shopfloor
pytest tests/test_shopfloor_api.py::test_shopfloor_over_issue_rejected -v
```

> [!WARNING]
> На Windows не используйте пайплайны `2>&1 | head` — символ `2` может быть воспринят pytest как путь к файлу. Перенаправляйте в файл: `pytest tests/ -v > out.txt 2>&1`.

Профилирование: `backend/pytest.ini` выводит 10 самых медленных тестов (`--durations=10`).