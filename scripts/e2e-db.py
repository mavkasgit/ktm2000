"""БД E2E-стенда: привести к репозиторию и не дать задеть чужую dev-БД (#220, #225).

Зачем
-----
Стенд E2E работает на **отдельной** базе ``ktm2000_e2e`` на тестовом
Postgres (5441). Общая dev-БД (5440) принадлежит основному дереву и параллельной
работе, и прогон E2E по ней задевает чужое состояние.

Поэтому команда ``ensure`` начинает не с подключения, а с проверки DSN из
``.env.e2e``: имя базы и пара host:port не должны совпадать с dev-конфигом.
Отказ — до подключения, код возврата 2, чтобы отличить его от сетевой ошибки.

Автобарьер накопительной БД (#225)
----------------------------------
БД стенда **накопительная**: ``apiResetAll()`` чистит производственные таблицы,
но не справочник сырья и не всё, что накопили прошлые прогоны. Своей
самовосстановительности у неё нет, поэтому вердикт прогона может зависеть от
данных, оставшихся от чужой версии кода. Реальный класс — «красный по вине
данных стенда»: сохранённые ``production_routes`` от промежуточной итерации
работы дают ``route_signature_conflict`` (имя маршрута совпало, сигнатура — нет)
на импорте, который на чистой БД проходит без единого конфликта.

Поэтому ``ensure`` сверяет существующую БД с репозиторием по двум признакам,
между которыми больше нечего проверять, и пересоздаёт её при расхождении,
печатая причину:

(а) ``alembic_version`` в БД не равен head из ``backend/alembic/versions`` —
    схема стенда отстала от кода (или в БД попала ревизия, которой в
    репозитории уже нет).
(б) версия правил сборки маршрута: sha256 исходников, из которых собираются
    имя и сигнатура маршрута (``route_name_builder.py``, ``route_builder.py``,
    ``route_signature.py``, сиды профилей и правил выбора). Меняется шаблон
    имени или состав этапов — и сохранённые маршруты становятся чужими, а
    пересборки у них нет: пересоздаёт их только импорт. Отметка лежит в БД в
    таблице ``e2e_stand_stamp``; таблицы нет — версия неизвестна, БД
    пересоздаётся (один раз за жизнь стенда).

Отказ от пересоздания — флаг ``--keep`` или ``E2E_DB_KEEP=1``: причина
печатается, БД остаётся как есть. Удаления БД молча не происходит: причина
всегда в выводе.

    python scripts/e2e-db.py ensure [--env-file <path>] [--keep]

Составные части DSN (host/port/user/password) берутся из самого ``.env.e2e`` —
дублировать их в скрипте нечего.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import hashlib
import os
import re
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

#: Базы, которые нельзя пересоздавать ни при каком расхождении: служебные.
PROTECTED_DB_NAMES = {"postgres", "template0", "template1"}

ALEMBIC_VERSIONS_DIR = REPO_ROOT / "backend" / "alembic" / "versions"

#: Исходники, из которых собираются имя и сигнатура маршрута. Их версия —
#: признак (б): изменились — сохранённые в БД стенда маршруты принадлежат
#: прежней версии кода, и импорт будет конфликтовать сам с собой.
ROUTE_RULES_SOURCES = (
    "backend/app/services/route_name_builder.py",
    "backend/app/services/route_builder.py",
    "backend/app/services/route_signature.py",
    "backend/app/seeds/route_rule_profiles.py",
    "backend/app/seeds/selection_rules.py",
)

STAMP_TABLE = "e2e_stand_stamp"
STAMP_ROUTE_RULES = "route_rules_digest"
"""Ключ отметки версии правил сборки маршрута в ``e2e_stand_stamp``."""

EXIT_GUARD = 2
EXIT_ERROR = 1
CONNECT_TIMEOUT_SECONDS = 15
ADMIN_DATABASE = "postgres"


class StandTargetError(Exception):
    """DSN стенда указывает на чужую БД — подключаться нельзя."""


class StandRepoError(Exception):
    """Репозиторий не даёт посчитать версию стенда — сравнивать нечем."""


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
    if name in PROTECTED_DB_NAMES:
        # Пересоздание (DROP DATABASE) служебной базы — не то, чем стенд
        # готовит свою БД, даже если DSN от dev-конфига не отличить.
        raise StandTargetError(
            f"стенд нацелен на служебную базу {name!r} ({dsn}). "
            "Пересоздавать её нельзя: укажи отдельную базу стенда, например ktm2000_e2e."
        )
    return dsn


# --- версия репозитория: с чем сверяется существующая БД стенда ---


def _module_literal(source: str, name: str) -> object:
    """Значение присваивания `name = …` в модуле миграции, без импорта alembic."""
    match = re.search(
        rf"^{re.escape(name)}(?:\s*:\s*[^=\n]+)?\s*=\s*(.+?)\s*$",
        source,
        re.MULTILINE,
    )
    if match is None:
        raise StandRepoError(f"в модуле миграции нет присваивания {name}")
    raw = match.group(1)
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw.strip("'\"")


def repo_alembic_heads(versions_dir: Path = ALEMBIC_VERSIONS_DIR) -> set[str]:
    """Head-ревизии из `backend/alembic/versions` (без запуска alembic)."""
    if not versions_dir.is_dir():
        raise StandRepoError(f"каталог миграций {versions_dir} не найден")
    revisions: set[str] = set()
    revises: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        revision = _module_literal(source, "revision")
        if not isinstance(revision, str) or not revision:
            raise StandRepoError(f"{path.name}: нечитаемый revision={revision!r}")
        revisions.add(revision)
        down = _module_literal(source, "down_revision")
        if down is None:
            continue
        for parent in down if isinstance(down, (tuple, list)) else (down,):
            revises.add(str(parent))
    if not revisions:
        raise StandRepoError(f"в {versions_dir} нет ни одной ревизии")
    unknown = revises - revisions
    if unknown:
        raise StandRepoError(
            f"миграция ссылается на отсутствующие ревизии {sorted(unknown)} — "
            "цепочка миграций в репозитории разорвана"
        )
    heads = {rev for rev in revisions if rev not in revises}
    if len(heads) != 1:
        raise StandRepoError(
            f"в репозитории {len(heads)} head-ревизий {sorted(heads)}: "
            "`alembic upgrade head` на такой цепочке не пройдёт, и сверять с ней нечего"
        )
    return heads


def route_rules_digest(repo_root: Path = REPO_ROOT) -> str:
    """Версия правил сборки имени и сигнатуры маршрута (признак (б))."""
    digest = hashlib.sha256()
    for relative in ROUTE_RULES_SOURCES:
        path = repo_root / relative
        if not path.is_file():
            raise StandRepoError(
                f"нет {relative} — версию правил сборки маршрута нечем посчитать"
            )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


# --- работа с БД ---


async def _read_stamp(conn: asyncpg.Connection) -> dict[str, str]:
    """Отметки версий из `e2e_stand_stamp` (пусто, если таблицы нет)."""
    exists = await conn.fetchval("SELECT to_regclass($1)", STAMP_TABLE)
    if not exists:
        return {}
    rows = await conn.fetch(f"SELECT key, value FROM {STAMP_TABLE}")
    return {row["key"]: row["value"] for row in rows}


async def _write_stamp(conn: asyncpg.Connection, values: dict[str, str]) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {STAMP_TABLE} (
            key text PRIMARY KEY,
            value text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for key, value in values.items():
        await conn.execute(
            f"""
            INSERT INTO {STAMP_TABLE} (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key,
            value,
        )


async def _stamp_stand(dsn: str, route_rules: str) -> None:
    """Отметить текущую версию репозитория в только что созданной БД стенда."""
    conn = await asyncpg.connect(
        _asyncpg_dsn(dsn, _db_name(dsn)), timeout=CONNECT_TIMEOUT_SECONDS
    )
    try:
        await _write_stamp(conn, {STAMP_ROUTE_RULES: route_rules})
    finally:
        await conn.close()


async def _drift_reasons(dsn: str, repo_head: str, route_rules: str) -> list[str]:
    """Причины, по которым существующая БД стенда не совпадает с репозиторием."""
    name = _db_name(dsn)
    conn = await asyncpg.connect(_asyncpg_dsn(dsn, name), timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        reasons: list[str] = []
        has_version_table = await conn.fetchval("SELECT to_regclass('alembic_version')")
        if not has_version_table:
            reasons.append(
                "в БД нет таблицы alembic_version — миграции на неё ни разу не накатывали"
            )
        else:
            versions = [row["version_num"] for row in await conn.fetch("SELECT version_num FROM alembic_version")]
            if repo_head not in versions:
                reasons.append(
                    f"версия миграций в БД {sorted(versions) or '—'} "
                    f"не равна head репозитория {repo_head}"
                )
        stored = await _read_stamp(conn)
        stamp = stored.get(STAMP_ROUTE_RULES)
        if stamp is None:
            reasons.append(
                f"в БД нет отметки версии правил сборки маршрута ({STAMP_TABLE}) — "
                "её версия неизвестна, сохранённые маршруты могут быть от прежнего кода"
            )
        elif stamp != route_rules:
            reasons.append(
                f"версия правил сборки маршрута в БД {stamp} "
                f"не равна версии репозитория {route_rules}"
            )
        return reasons
    finally:
        await conn.close()


async def _create_database(dsn: str, name: str) -> None:
    """Создать БД стенда заново (существующей по имени быть не должно)."""
    admin = await asyncpg.connect(
        _asyncpg_dsn(dsn, ADMIN_DATABASE), timeout=CONNECT_TIMEOUT_SECONDS
    )
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


async def _recreate_database(dsn: str, name: str) -> None:
    """Пересоздать БД стенда: сбросить подключения, DROP, CREATE."""
    admin = await asyncpg.connect(
        _asyncpg_dsn(dsn, ADMIN_DATABASE), timeout=CONNECT_TIMEOUT_SECONDS
    )
    try:
        # Живой стенд держит подключения к своей БД, и DROP без этого падает.
        await admin.execute(
            """
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()
            """,
            name,
        )
        await admin.execute(f'DROP DATABASE "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


async def ensure_database(dsn: str, *, keep: bool = False) -> None:
    name = _db_name(dsn)
    repo_head = next(iter(repo_alembic_heads()))
    route_rules = route_rules_digest()

    conn = await asyncpg.connect(
        _asyncpg_dsn(dsn, ADMIN_DATABASE), timeout=CONNECT_TIMEOUT_SECONDS
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
    finally:
        await conn.close()

    if not exists:
        await _create_database(dsn, name)
        await _stamp_stand(dsn, route_rules)
        print(
            f"E2E-БД {name}: создана (head {repo_head}, правила маршрута {route_rules}); "
            f"дальше — db:e2e:migrate и db:e2e:seed"
        )
        return

    reasons = await _drift_reasons(dsn, repo_head, route_rules)
    if not reasons:
        print(
            f"E2E-БД {name}: совпадает с репозиторием "
            f"(head {repo_head}, правила маршрута {route_rules}) — не трогаю"
        )
        return

    print(f"E2E-БД {name}: расхождение с репозиторием —")
    for reason in reasons:
        print(f"  • {reason}")
    if keep:
        print(
            "  пересоздание отменено (--keep / E2E_DB_KEEP): БД оставлена как есть, "
            "прогон может краснеть на данных стенда"
        )
        return
    await _recreate_database(dsn, name)
    await _stamp_stand(dsn, route_rules)
    print(
        f"E2E-БД {name}: пересоздана под репозиторий (head {repo_head}, "
        f"правила маршрута {route_rules}); дальше — db:e2e:migrate и db:e2e:seed"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка БД E2E-стенда")
    parser.add_argument("command", choices=["ensure"])
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"env-файл стенда (по умолчанию {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        default=os.environ.get("E2E_DB_KEEP") == "1",
        help="не пересоздавать БД при расхождении с репозиторием (то же — E2E_DB_KEEP=1)",
    )
    args = parser.parse_args(argv)

    try:
        dsn = resolve_stand_dsn(args.env_file)
        repo_alembic_heads()
        route_rules_digest()
    except StandTargetError as exc:
        print(f"[e2e-db] ОТКАЗ: {exc}", file=sys.stderr)
        return EXIT_GUARD
    except StandRepoError as exc:
        print(f"[e2e-db] нечем сверять БД стенда с репозиторием: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        asyncio.run(ensure_database(dsn, keep=args.keep))
    except Exception as exc:  # noqa: BLE001 — CLI: причина попадает в сообщение
        print(f"[e2e-db] не удалось подготовить БД стенда: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return 0


if __name__ == "__main__":
    sys.exit(main())
