"""БД E2E-стенда: создать, если её нет, и не дать задеть чужую dev-БД (#220).

Зачем
-----
Стенд E2E работает на **отдельной** базе ``ktm2000_e2e`` на тестовом
Postgres (5441). Общая dev-БД (5440) принадлежит основному дереву и параллельной
работе, и прогон E2E по ней задевает чужое состояние.

Поэтому команда ``ensure`` начинает не с подключения, а с проверки DSN из
``.env.e2e``: имя базы и пара host:port не должны совпадать с dev-конфигом.
Отказ — до подключения, код возврата 2, чтобы отличить его от сетевой ошибки.

    python scripts/e2e-db.py ensure [--env-file <path>]

Составные части DSN (host/port/user/password) берутся из самого ``.env.e2e`` —
дублировать их в скрипте нечего.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env.e2e"
DEV_ENV_FILE = REPO_ROOT / ".env.dev"

# Подстраховка на случай, если `.env.dev` локально отсутствует или переименован.
FALLBACK_DEV_DB_NAMES = {"ktm2000_dev"}
FALLBACK_DEV_ENDPOINTS = {("localhost", 5440), ("127.0.0.1", 5440)}

EXIT_GUARD = 2
EXIT_ERROR = 1
CONNECT_TIMEOUT_SECONDS = 15
ADMIN_DATABASE = "postgres"


class StandTargetError(Exception):
    """DSN стенда указывает на чужую БД — подключаться нельзя."""


def read_env_file(path: Path) -> dict[str, str]:
    """Минимальный разбор `KEY=VALUE` (без dotenv: скрипт должен работать сам)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _db_name(dsn: str) -> str:
    return urlparse(dsn).path.lstrip("/")


def _endpoint(dsn: str) -> tuple[str, int]:
    parsed = urlparse(dsn)
    return parsed.hostname or "localhost", parsed.port or 5432


def _asyncpg_dsn(dsn: str, database: str) -> str:
    """DSN в том виде, который понимает asyncpg.

    Приложение работает со SQLAlchemy-строкой (`postgresql+asyncpg://…`), а
    драйвер такой схемы не знает и падает на разборе, не доходя до сети.
    """
    parsed = urlparse(dsn)
    scheme = parsed.scheme.split("+", 1)[0]
    userinfo = ""
    if parsed.username:
        userinfo = f"{parsed.username}:{parsed.password or ''}@"
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{scheme}://{userinfo}{host}{port}/{database}"


def dev_databases(env_file: Path) -> tuple[set[str], set[tuple[str, int]]]:
    """Имена баз и endpoint'ы, которые заняты devstack'ом."""
    names = set(FALLBACK_DEV_DB_NAMES)
    endpoints = set(FALLBACK_DEV_ENDPOINTS)
    if not env_file.is_file():
        return names, endpoints
    dev = read_env_file(env_file)
    dsn = dev.get("DATABASE_URL")
    if dsn:
        names.add(_db_name(dsn))
        endpoints.add(_endpoint(dsn))
    else:
        if dev.get("POSTGRES_DB"):
            names.add(dev["POSTGRES_DB"])
        if dev.get("DEV_POSTGRES_PORT"):
            endpoints.add(("localhost", int(dev["DEV_POSTGRES_PORT"])))
    return names, endpoints


def resolve_stand_dsn(env_file: Path, dev_env_file: Path = DEV_ENV_FILE) -> str:
    """DSN стенда из env-файла; при цели на dev-БД — `StandTargetError`."""
    if not env_file.is_file():
        raise StandTargetError(
            f"env-файл стенда {env_file} не найден: без него стенд не знает свою БД. "
            f"Ожидаемый путь — {DEFAULT_ENV_FILE}"
        )
    dsn = read_env_file(env_file).get("DATABASE_URL")
    if not dsn:
        raise StandTargetError(f"в {env_file} нет DATABASE_URL — стенд не знает свою БД")

    dev_names, dev_endpoints = dev_databases(dev_env_file)
    name = _db_name(dsn)
    if name in dev_names:
        raise StandTargetError(
            f"стенд нацелен на общую dev-БД {name!r} ({dsn}). "
            "Прогон E2E по ней задевает чужую работу: укажи отдельную базу, например ktm2000_e2e."
        )
    endpoint = _endpoint(dsn)
    if endpoint in dev_endpoints:
        raise StandTargetError(
            f"стенд нацелен на Postgres devstack {endpoint[0]}:{endpoint[1]} — общий с ним. "
            "Прогон E2E по нему задевает чужую работу: возьми тестовый Postgres (5441)."
        )
    return dsn


async def ensure_database(dsn: str) -> None:
    name = _db_name(dsn)
    conn = await asyncpg.connect(
        _asyncpg_dsn(dsn, ADMIN_DATABASE), timeout=CONNECT_TIMEOUT_SECONDS
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            print(f"E2E-БД {name}: уже существует (миграции догонят её)")
            return
        await conn.execute(f'CREATE DATABASE "{name}"')
        print(f"E2E-БД {name}: создана")
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка БД E2E-стенда")
    parser.add_argument("command", choices=["ensure"])
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"env-файл стенда (по умолчанию {DEFAULT_ENV_FILE})",
    )
    args = parser.parse_args(argv)

    try:
        dsn = resolve_stand_dsn(args.env_file)
    except StandTargetError as exc:
        print(f"[e2e-db] ОТКАЗ: {exc}", file=sys.stderr)
        return EXIT_GUARD
    try:
        asyncio.run(ensure_database(dsn))
    except Exception as exc:  # noqa: BLE001 — CLI: причина попадает в сообщение
        print(f"[e2e-db] не удалось подготовить БД стенда: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return 0


if __name__ == "__main__":
    sys.exit(main())
