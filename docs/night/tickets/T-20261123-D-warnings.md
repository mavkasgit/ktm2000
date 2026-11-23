# T-20261123-D — разбор 4 warnings базового прогона pytest

**Ветка:** `night/2026-11-23-d` · **Worktree:** `C:/Users/LogoPrint/VibeCoding/ktm2000-night-d`
**Базовый прогон:** `PYTEST_NUM_WORKERS=4 npm run test:pytest` — 2554 passed, 490.39s, 4 warnings.
**Срезаная зона:** только `backend/tests/test_backups_path_traversal.py`, при необходимости
`backend/tests/conftest.py`, и этот тикет. `backend/app/**` и чужие тесты не трогались.

---

## Задача 1 — `PytestUnhandledThreadExceptionWarning` в backup-тесте: STATUS FIXED

### Воспроизведение

Тест: `backend/tests/test_backups_path_traversal.py::test_backup_file_path_rejects_symlink_escape`.
Launcher из своего worktree, `PYTEST_NUM_WORKERS=2`, `TEST_PYTHON=.../ktm2000/backend/.venv/Scripts/python.exe`:

```
npm run test:pytest -- -k test_backup_file_path_rejects_symlink_escape
```

**ДО правки** (Run ID `14ea4815cb53`):

```
C:\...\_pytest\threadexception.py:54: PytestUnhandledThreadExceptionWarning: Exception in thread Thread-1 (_readerthread)
  ...
  File "...\subprocess.py", line 1614, in _readerthread
    buffer.append(fh.read())
  File "<frozen codecs>", line 325, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa4 in position 3: invalid start byte
============================= 1 passed, 1 warning in 20.59s ==============================
```

**ПОСЛЕ правки** (Run ID `a7a6144a3c2f`):

```
============================== 1 passed in 9.72s ==============================
```

Warning исчез (`1 warning` → нет секции warnings summary), результат тот же (`1 passed`).
Exit code launcher'а — `0` в обоих прогонах.

### Корень

В `_make_escape_link` (строка 35) `subprocess.run([... "mklink", "/J" ...],
capture_output=True, text=True, check=False)` читает вывод `cmd.exe` через
`_readerthread` и декодирует его **жёстко в UTF-8** (режим локали Python 3.14 на этой
машине). На русской Windows `mklink` печатает сообщение в консольной кодировке
(cp866/cp1252), там встречается байт `0xa4`, который в UTF-8 невалиден. Поток чтения
падает с `UnicodeDecodeError` **в фоновом потоке**, pytest превращает это в
`PytestUnhandledThreadExceptionWarning`. Сам тест при этом проходил — дефект был
именно в инфраструктуре чтения вывода.

### Правка

`text=True` заменено на `encoding="utf-8", errors="replace"` (capture_output и
check=False сохранены). `errors="replace"` гарантирует, что любой невалидный байт
заменяется на U+FFFD вместо исключения; смысл skip-сообщения
(`symlink=...; junction=<вывод mklink>`) сохраняется — он по-прежнему печатает оба
вывода (от symlink и от junction), просто без возможности уронить тест. Продуктовая семантика не
затронута: хелпер `_backup_file_path` и эндпоинты не менялись.

---

## Задача 2 — `SAWarning: fully NULL primary key identity cannot load any object`: STATUS BLOCKED_NEEDS_HUMAN

Воспроизведение (оба теста разом, Run ID `3d7d589f115d`):

```
npm run test:pytest -- -k "test_stale_token_when_branch_changed_between_preview_and_confirm or test_e2e_excel_import_creates_routes_with_steps"
...
tests/test_e2e_route_import.py::test_e2e_excel_import_creates_routes_with_steps
tests/reversal/test_replay_core.py::test_stale_token_when_branch_changed_between_preview_and_confirm
  <sys>:0: SAWarning: fully NULL primary key identity cannot load any object.  This condition may raise an error in a future release.
======================== 2 passed, 2 warnings in 14.26s ========================
```

Точки вызова найдены переводом warning в ошибку (`-W "error::sqlalchemy.exc.SAWarning"`):

### Корень 2a — `app/reversal/stock_compensator.py:308` (продовый код, вне зоны)

```
app\reversal\service.py:758: in amend
    fresh_preview = await self.preview_amend(
app\reversal\service.py:682: in preview_amend
    check = await node_comp.check(
app\reversal\stock_compensator.py:308: in check
    transfer = await db.get(Transfer, ref_id)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
...
E sqlalchemy.exc.SAWarning: fully NULL primary key identity cannot load any object.
```

Тест создаёт `Action(action_type="transfer_send", ref_id=None, ...)` как «нового
активного dependent» (`test_replay_core.py:428-432`), после чего `preview_amend`
вызывает `check()` на этом action. `ref_id` равен `None`, и `db.get(Transfer, None)`
заставляет SQLAlchemy предупредить о полностью NULL-RK identity.

**Почему не чиню:** правка лежит в `backend/app/reversal/stock_compensator.py` —
запрещённая зона (только тесты + conftest). Нужна осознанная правка прода: либо
пропускать `db.get`, когда `ref_id is None`, либо явно обрабатывать случай
«action без ref_id» в `StockCompensator.check`. Это меняет продуктовую семантику
и требует своего тикета/ревью.

### Корень 2b — `tests/test_e2e_route_import.py:243` (тест, но тоже вне зоны)

```
tests\test_e2e_route_import.py:243: in test_e2e_excel_import_creates_routes_with_steps
    section = await session.get(Section, step.section_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
...
E sqlalchemy.exc.SAWarning: fully NULL primary key identity cannot load any object.
```

Импорт создаёт `RouteStage` с `section_id=None` (плейсхолдеры шагов). Тест всё равно
вызывает `db.get(Section, None)`, хотя ниже сам же обрабатывает отсутствие секции:
`section_code = section.code if section else "?"` (строка 244).

**Почему не чиню:** `backend/tests/test_e2e_route_import.py` не входит в список
разрешённых файлов среза D (разрешены только `test_backups_path_traversal.py` и
`conftest.py`). Минимальный фикс был бы:
```python
section = await session.get(Section, step.section_id) if step.section_id else None
```
но он за пределами зоны — нужен отдельный тикет или разрешение оркестратора.

### Итог по задаче 2

Оба предупреждения — воспроизводимые, корни локализованы с точностью до строки.
Ни один не исправлен: оба лежат вне зоны файлов этого среза, а правка 2a вообще
касается продуктовой логики. Передаётся как `BLOCKED_NEEDS_HUMAN`.

---

## Изменённые файлы

* `backend/tests/test_backups_path_traversal.py` — правка декодирования вывода `mklink` (задача 1).
* `docs/night/tickets/T-20261123-D-warnings.md` — этот тикет.

`backend/tests/conftest.py` не изменялся. Временные логи прогонов (`_night_d_*.log`)
создавались в корне worktree, но попадают под `.gitignore:*.log` и удалены.
