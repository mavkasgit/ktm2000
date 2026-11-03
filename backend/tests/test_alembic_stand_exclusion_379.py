"""#379: `alembic check` на базе e2e-стенда не шумит на служебной таблице стенда.

Механика, которую сторожит файл. `scripts/e2e-db.py` создаёт ``e2e_stand_stamp``
сырым SQL (`_write_stamp`), мимо Alembic и мимо моделей: это отметка версии
репозитория в БД клона прогона, а не продукт. Пока `backend/alembic/env.py` не
исключал её в `include_object`, autogenerate видел в БД стенда таблицу, которой
нет в `Base.metadata`, и каждый прогон `alembic check` давал
`remove_table e2e_stand_stamp` / `FAILED: New upgrade operations detected`.
Шум ломал и то, и другое: скриптовый прогон проверки всегда красный, агент
учится игнорировать красный вывод (PLAYBOOK §10.7, открытый вопрос прошлой
ночи).

Исключение само по себе правлено раньше (коммит `013ca53a`, тот же механизм,
что `MIGRATION_HELPER_TABLES` из #261), но **проверки на нём не было**: список
`env.py` держался на договорённости. Здесь два сторожа:

1. `test_service_table_exclusion_does_not_cover_model_tables` — дешёвый:
   имя, которым стенд сам называет свою служебную таблицу, не должно быть
   моделью продукта. Иначе «исключение» превратится в способ спрятать
   реальное расхождение схемы (именно этот риск и делает такие списки
   опасными).
2. `test_alembic_check_stays_green_on_stand_table_and_fails_on_drift` —
   сквозной, на живой базе: `upgrade head`, затем таблица создаётся **кодом
   самого стенда** (`_write_stamp`), значит при переименовании `STAMP_TABLE`
   проверка покраснеет и рассинхрон имени поймает. Дальше проверяется
   способность падать: реально лишняя таблица обязана давать красный
   `remove_table`, а после её удаления — снова зелёный. Иначе «исправление»
   означало бы, что `alembic check` просто перестал что-либо видеть.

`slow`: тест поднимает отдельную миграционную базу (`ktm_mig_*`) и трижды
гоняет `alembic check` — замеры в комментарии к тикету, ~35 с; дефолтный
прогон launcher'а его пропускает, `--full` и CI — нет.
"""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest
from app.models.base import Base

from tests.helpers.mig_db import (
    BACKEND_DIR,
    alembic_command,
    alembic_env,
    create_migration_db,
    drop_migration_db,
    migration_db_reachable,
)

pytestmark = pytest.mark.skipif(
    not migration_db_reachable(),
    reason="PostgreSQL server not reachable for migration test",
)

#: Таблица-проба, которой проверяется, что `alembic check` остался способным
#: краснеть. В исключения `include_object` она не входит и вход не должна.
DRIFT_PROBE_TABLE = "zzz_alembic_drift_probe"

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_stand_module() -> ModuleType:
    """Загрузить `scripts/e2e-db.py` (имя с дефисом — обычный import невозможен).

    Хелпер берётся у самого стенда, а не переписывается здесь: иначе тест
    проверял бы свою копию DDL и не заметил бы переименование таблицы стендом.
    """
    path = _SCRIPTS_DIR / "e2e-db.py"
    spec = importlib.util.spec_from_file_location("e2e_db_probe", path)
    if spec is None or spec.loader is None:
        pytest.fail(f"не удалось загрузить {path}", pytrace=False)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _to_asyncpg_dsn(url: str) -> str:
    """DSN SQLAlchemy (`postgresql+asyncpg://`) → DSN asyncpg."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _run_alembic(args: tuple[str, ...], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Вызвать alembic и вернуть результат целиком (код возврата важен тесту)."""
    return subprocess.run(
        alembic_command(*args),
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_service_table_exclusion_does_not_cover_model_tables() -> None:
    """Служебная таблица стенда не является моделью — её можно исключать.

    Если кто-то заведёт `e2e_stand_stamp` как ORM-модель, исключение в
    `include_object` прячет её из autogenerate навсегда, и реальное расхождение
    (переименование колонки, потерянный индекс) станет невидимым. Этот тест
    краснеет в тот момент, когда имя уходит из разряда «создано не Alembic».
    """
    stand = _load_stand_module()
    service_table = str(stand.STAMP_TABLE)
    model_tables = {table.name for table in Base.metadata.tables.values()}
    assert service_table not in model_tables, (
        f"`{service_table}` объявлена как модель продукта — её нельзя держать "
        "в исключениях `backend/alembic/env.py:STAND_SERVICE_TABLES`, иначе "
        "alembic перестанет видеть её расхождения"
    )


@pytest.mark.slow
def test_alembic_check_stays_green_on_stand_table_and_fails_on_drift(tmp_path: Path) -> None:
    """`alembic check` зелёный с таблицей стенда и красный с реальной дырой."""
    asyncio.run(_exercise_stand_and_drift(tmp_path))


async def _exercise_stand_and_drift(tmp_path: Path) -> None:
    """Тело проверки (async-часть вызывается из синхронного теста).

    Синхронная обёртка нужна, а не `async def`: внутри крутится блокирующий
    `subprocess.run` (alembic), и в async-тесте он попал бы под `ASYNC221` —
    тот же осознанный sync-запуск, что у `tests/test_migrations.py`.
    """
    stand = _load_stand_module()
    db_name, target_url = await create_migration_db()
    env = alembic_env(target_url, tmp_path)
    try:
        upgrade = _run_alembic(("upgrade", "head"), env)
        assert upgrade.returncode == 0, upgrade.stderr or upgrade.stdout

        conn = await asyncpg.connect(_to_asyncpg_dsn(target_url))
        try:
            # Таблица стенда — руками самого стенда, не копией DDL из теста.
            await stand._write_stamp(conn, {"repo_head": "379-probe"})
            assert await conn.fetchval("SELECT to_regclass($1)", str(stand.STAMP_TABLE)), (
                "стенд не создал служебную таблицу — проверять нечего"
            )
            with_stand = _run_alembic(("check",), env)
            assert with_stand.returncode == 0, (
                "alembic check краснеет из-за служебной таблицы стенда — исключение "
                f"в backend/alembic/env.py не работает: {with_stand.stdout} {with_stand.stderr}"
            )
            assert str(stand.STAMP_TABLE) not in with_stand.stdout, (
                "шум вернулся: check снова упоминает таблицу стенда"
            )

            await conn.execute(f"CREATE TABLE {DRIFT_PROBE_TABLE} (id integer PRIMARY KEY)")
            drifted = _run_alembic(("check",), env)
            assert drifted.returncode != 0, (
                "alembic check перестал видеть реальное расхождение — проверка не "
                "способна падать, а значит не является защитой"
            )
            assert DRIFT_PROBE_TABLE in drifted.stdout + drifted.stderr, (
                f"красный вывод не про лишнюю таблицу {DRIFT_PROBE_TABLE}: {drifted.stdout}"
            )

            await conn.execute(f"DROP TABLE {DRIFT_PROBE_TABLE}")
            restored = _run_alembic(("check",), env)
            assert restored.returncode == 0, restored.stdout or restored.stderr
        finally:
            await conn.close()
    finally:
        await drop_migration_db(db_name)
