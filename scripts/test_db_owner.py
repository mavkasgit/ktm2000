"""Owner-таблица тестовых БД KTM-2000 — единственный источник правды.

Owner-таблица ``ktm2000_test_owner`` (в служебной БД ``postgres``) связывает
имя тестовой базы со временем её создания: по ней TTL-уборка
(``scripts/test-db.py cleanup``) отличает осиротевшую базу от живой, а
``drop <db>`` — свою базу от чужой.

Имена в таблице бывают двух видов:

* ``ktm2000_test_<12 hex>`` — run-DB лаунчера ``scripts/test-run.ps1``;
* ``ktm_mig_<10 hex>`` — одноразовая база миграционного теста
  (``tests/test_migrations.py``, ``tests/test_hanger_norm_key_migration_218.py``
  через хелпер ``tests/helpers/mig_db.py``).

``run_id`` базы миграционного теста — само имя базы: оно уже уникально на базу,
а срез префикса run-DB от такого имени даёт мусор из последних символов и один
и тот же ключ на все ``ktm_mig_*``.

Модуль без зависимостей (только stdlib), потому что его импортируют и CLI
``scripts/test-db.py``, и pytest-хелпер. Имя — без дефиса: сам CLI называется
``test-db.py`` и импортирован быть не может.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

RUN_DB_PREFIX = "ktm2000_test_"
RUN_DB_RE = re.compile(r"^ktm2000_test_[0-9a-f]{12}$")

MIG_DB_PREFIX = "ktm_mig_"
MIG_DB_RE = re.compile(r"^ktm_mig_[0-9a-f]{10}$")

#: Таблица владельцев тестовых баз (служебная БД ``postgres``).
OWNER_TABLE = "ktm2000_test_owner"

#: DDL owner-таблицы и индекса по ``created_at`` (по нему считает TTL-cleanup).
OWNER_TABLE_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {OWNER_TABLE} (
        run_id        text PRIMARY KEY,
        db_name       text UNIQUE NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now(),
        last_seen_at  timestamptz
    )
    """,
    f"CREATE INDEX IF NOT EXISTS {OWNER_TABLE}_created_at_idx "
    f"ON {OWNER_TABLE} (created_at)",
)


def run_id_from_db_name(db_name: str) -> str:
    """``run_id`` (PRIMARY KEY owner-таблицы) по имени тестовой базы.

    У run-DB — хвост после ``ktm2000_test_``; у базы миграционного теста —
    само имя. Имя не тестовой базы — ошибка, а не «срез чего получилось».
    """
    if RUN_DB_RE.fullmatch(db_name):
        return db_name[len(RUN_DB_PREFIX):]
    if MIG_DB_RE.fullmatch(db_name):
        return db_name
    raise ValueError(f"Not a test database name: {db_name!r}")


async def ensure_owner_table(conn: asyncpg.Connection) -> None:
    """Создать owner-таблицу с индексом (идемпотентно)."""
    for statement in OWNER_TABLE_DDL:
        await conn.execute(statement)


async def insert_owner_row(conn: asyncpg.Connection, db_name: str) -> None:
    """Зарегистрировать базу: owner-строку пишут ДО ``CREATE DATABASE``.

    Тогда прерванный прогон оставляет либо ничего, либо базу, которую видит
    ``cleanup``/``drop``; обратный порядок оставлял бы базу без владельца.
    """
    await conn.execute(
        f"INSERT INTO {OWNER_TABLE} (run_id, db_name) VALUES ($1, $2) "
        "ON CONFLICT (run_id) DO NOTHING",
        run_id_from_db_name(db_name),
        db_name,
    )


async def delete_owner_row(conn: asyncpg.Connection, db_name: str) -> None:
    """Снять регистрацию базы (по ``db_name`` — он в таблице UNIQUE)."""
    await conn.execute(f"DELETE FROM {OWNER_TABLE} WHERE db_name = $1", db_name)
