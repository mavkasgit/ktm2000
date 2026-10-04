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

Шаблонная БД и клон на прогон (#281)
------------------------------------
``ensure`` + ``db:e2e:migrate`` + ``db:e2e:seed`` на каждый прогон — это минуты
на запуск. ``prep`` делает то же самое **один раз**: собирает шаблонную БД
(``<база>_template``) с миграциями и сидами и сверяет её с репозиторием теми же
двумя признаками, что ``ensure`` (head миграций + версия правил маршрута,
отметка в ``e2e_stand_stamp``). Дальше каждый прогон получает **клон**
(``CREATE DATABASE … TEMPLATE …``) со своим именем
``<база>_run_<stamp>_<run-id>`` и своим env-файлом со сменённым ``DATABASE_URL``
— прогоны больше не делят одну базу, а ``apiResetAll()`` чистит свою.

    python scripts/e2e-db.py prep --run-id <id>     # E2E_RUN_ID
    python scripts/e2e-db.py drop --run-id <id>
    python scripts/e2e-db.py drop --stale-run-minutes 180

``prep`` печатает ``E2E_RUN_ENV_FILE=<path>`` — этот файл обёртка прогона
передаёт дальше как ``E2E_ENV_FILE``. ``drop`` удаляет клон и его env-файл;
``--stale-run-minutes`` сносит клоны брошенных прогонов по метке времени в
имени. Брошенный шаблон не пересобирается молча: ``--keep-template``
(``E2E_TEMPLATE_KEEP=1``) оставляет его как есть, печатая причину, — как
``--keep`` у ``ensure``.

По клону на воркера (#289)
--------------------------
Один клон на прогон закрывает параллельные **прогоны**, но не параллельные
**воркеры** одного прогона: они делят этот клон, а ``apiResetAll()`` —
``TRUNCATE … CASCADE``, поэтому воркер сносит данные соседа (и наоборот).
Поэтому ``prep --workers N`` (он же ``E2E_WORKERS=N``) клонирует шаблон
``N`` раз: ``<база>_run_<stamp>_<run-id>_w0``, ``_w1``, …, и каждому
воркеру достаётся своя БД и свой env-файл. При ``N == 1`` имена прежние.
``drop --run-id`` снимает все клоны прогона разом.

Составные части DSN (host/port/user/password) берутся из самого ``.env.e2e`` —
дублировать их в скрипте нечего.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[1]


# Env-файл стенда переопределяется через `E2E_ENV_FILE`: у каждого worktree
# своя БД стенда, иначе параллельные прогоны бьют в одну базу и стирают данные
# друг друга (см. `frontend/e2e/AGENTS.md`, «Правила параллельной работы
# агентов»).
def _stand_env_file() -> Path:
    """Env-файл стенда: `E2E_ENV_FILE` (относительный — от корня репозитория)."""
    raw = os.environ.get("E2E_ENV_FILE")
    if not raw:
        return REPO_ROOT / ".env.e2e"
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


DEFAULT_ENV_FILE = _stand_env_file()
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
    # Канон участков и операций: SECTION_OPS и TRANSFORMING_SECTION_OPS
    # отсюда попадают в профили и правила через canon/registry, и правка
    # этого файла меняет собираемые имя и сигнатуру маршрута. Без него в
    # digest правка sections.py не видна, стенд не пересоздаётся, и маршруты
    # прежней версии кода конфликтуют сами с собой — инцидент с 13 ложными
    # route_signature_conflict (#226, разбор в комментарии к #225).
    "backend/app/seeds/sections.py",
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


# --- Шаблонная БД и клон на прогон (#281) ---

TEMPLATE_SUFFIX = "_template"
RUN_INFIX = "_run_"
#: Суффикс клона на воркера Playwright (#289). Один на все номера: `_w0`, `_w1`…
WORKER_SUFFIX = "_w"
RUN_ID_RE = re.compile(r"^[a-z0-9]{4,16}$")
RUN_STAMP_FORMAT = "%Y%m%d%H%M%S"
DEFAULT_STALE_RUN_MINUTES = 180


class StandRunError(Exception):
    """Подготовка клона на прогон не удалась — сообщение для человека."""


def validate_run_id(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise StandRunError(
            "не указан run-id клона: передай --run-id <id> или задай E2E_RUN_ID"
        )
    run_id = raw.strip().lower()
    if not RUN_ID_RE.match(run_id):
        raise StandRunError(
            f"run-id {raw!r} не годится: нужно 4–16 символов [a-z0-9] "
            "(он попадает в имя БД)"
        )
    return run_id


def template_db_name(base: str) -> str:
    return f"{base}{TEMPLATE_SUFFIX}"


def run_db_name(
    base: str,
    run_id: str,
    *,
    stamp: datetime | None = None,
    worker: int | None = None,
) -> str:
    """Имя клона; метка времени внутри имени — по ней `drop --stale` считает возраст.

    `worker` — номер воркера Playwright внутри прогона (#289): клон на
    воркера получает суффикс `_w<номер>`. Без суффикса (`worker=None`) имя
    прежнее, поэтому одиночный прогон и `drop --run-id` не меняются.
    """
    moment = stamp or datetime.now(tz=UTC)
    name = f"{base}{RUN_INFIX}{moment.strftime(RUN_STAMP_FORMAT)}_{run_id}"
    return f"{name}{WORKER_SUFFIX}{worker}" if worker is not None else name


def run_env_file_name(run_id: str, worker: int | None = None) -> str:
    """Имя env-файла клона. Суффикс воркера — как в имени самой БД (#289)."""
    if worker is None:
        return f".env.e2e.run.{run_id}.local"
    return f".env.e2e.run.{run_id}{WORKER_SUFFIX}{worker}.local"


def split_worker_suffix(db_name: str, base: str, run_id: str) -> int | None:
    """Номер воркера из имени клона (`None`, если клон без суффикса)."""
    prefix = f"{base}{RUN_INFIX}"
    if not db_name.startswith(prefix) or f"_{run_id}" not in db_name:
        return None
    _, _, tail = db_name.partition(f"_{run_id}")
    if not tail.startswith("_w"):
        return None
    digits = tail[2:]
    return int(digits) if digits.isdigit() else None


def dsn_with_database(dsn: str, name: str) -> str:
    """Тот же DSN, но с другим именем базы (endpoint и креды те же)."""
    return urlparse(dsn)._replace(path="/" + name).geturl()


def write_env_file_for_database(source: Path, target: Path, dsn: str) -> None:
    """Копия env-файла стенда, где DSN стенда заменён на DSN клона/шаблона.

    `E2E_TEST_DATABASE_URL` дописывается, если его в файле не было: alembic и
    сиды читают `DATABASE_URL`, а тесты стенда — вторую переменную.
    """
    keys = ("DATABASE_URL", "E2E_TEST_DATABASE_URL")
    out: list[str] = []
    replaced: set[str] = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.partition("=")[0].strip()
        if key in keys:
            out.append(f"{key}={dsn}")
            replaced.add(key)
        else:
            out.append(line)
    for key in keys:
        if key not in replaced:
            out.append(f"{key}={dsn}")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")


async def _admin_connection(dsn: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        _asyncpg_dsn(dsn, ADMIN_DATABASE), timeout=CONNECT_TIMEOUT_SECONDS
    )


async def _drop_database(admin: asyncpg.Connection, name: str) -> None:
    """Сбросить подключения и снести БД, если она есть.

    `WITH (FORCE)` (PG 13+) снимает чужие сессии сам, но между закрытием
    webServer и снятием базы процесс стенда успевает открыть новую сессию —
    поэтому повторяем: молча оставлять клон нельзя, его будет видно в списке
    баз и он занимает диск.
    """
    await admin.execute(
        """
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname = $1 AND pid <> pg_backend_pid()
        """,
        name,
    )
    for attempt in range(1, 4):
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            return
        except asyncpg.PostgresError as exc:
            if attempt == 3:
                raise
            print(
                f"[e2e-db] {name}: DROP не прошёл ({type(exc).__name__}), "
                f"повтор {attempt}/3"
            )
            await asyncio.sleep(1.0)


async def _clone_database(dsn: str, name: str, template: str) -> None:
    """Клон шаблона: `CREATE DATABASE … TEMPLATE …` (файловая копия, секунды)."""
    admin = await _admin_connection(dsn)
    try:
        # Остаток брошенного прогона с тем же run-id не должен мешать.
        await _drop_database(admin, name)
        await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    finally:
        await admin.close()


def _run_npm(script: str, env_file: Path) -> None:
    """`npm run <script>` с ENV_FILE/E2E_ENV_FILE на файл шаблонной БД.

    Команда идёт через обёртку `scripts/with-env-file.mjs` (её зовут сами
    npm-скрипты): alembic и сиды перекрывают `DATABASE_URL` содержимым файла
    (`apply_env_file(override=True)`), поэтому указать им базу можно **только**
    через env-файл, а не переменной окружения.
    """
    env = {**os.environ, "ENV_FILE": str(env_file), "E2E_ENV_FILE": str(env_file)}
    started = time.monotonic()
    proc = subprocess.run(
        f"npm run {script}",
        cwd=str(REPO_ROOT),
        env=env,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    took = time.monotonic() - started
    print(f"[e2e-db]   {script}: {took:.1f}s (код {proc.returncode})")
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-1000:]
        raise StandRunError(f"`npm run {script}` не прошёл (код {proc.returncode}):\n{tail}")


async def prepare_run(
    run_id: str,
    *,
    env_file: Path,
    keep_template: bool = False,
    stale_run_minutes: int = DEFAULT_STALE_RUN_MINUTES,
    workers: int = 1,
) -> int:
    """Шаблон + клон(ы) под прогон; печатает `E2E_RUN_ENV_FILE(S)` для обёртки.

    `workers > 1` — по клону на воркера Playwright (#289): без этого воркеры
    одного прогона делят базу, и `apiResetAll()` одного сносит данные другого.
    """
    dsn = resolve_stand_dsn(env_file)
    base = _db_name(dsn)
    repo_head = next(iter(repo_alembic_heads()))
    route_rules = route_rules_digest()

    template = template_db_name(base)
    template_dsn = dsn_with_database(dsn, template)
    template_env = env_file.parent / f".env.e2e.template.{base}.local"

    admin = await _admin_connection(dsn)
    try:
        template_exists = bool(
            await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", template)
        )
    finally:
        await admin.close()

    reasons: list[str] = []
    if not template_exists:
        reasons.append("шаблонной БД нет")
    else:
        reasons = await _drift_reasons(template_dsn, repo_head, route_rules)

    if reasons and keep_template:
        print(
            "[e2e-db] шаблон расходится с репозиторием, но взят как есть "
            "(--keep-template / E2E_TEMPLATE_KEEP=1):"
        )
        for reason in reasons:
            print(f"  • {reason}")
    elif reasons:
        print(f"[e2e-db] шаблон {template}: пересборка — {', '.join(reasons)}")
        started = time.monotonic()
        admin = await _admin_connection(dsn)
        try:
            await _drop_database(admin, template)
            await admin.execute(f'CREATE DATABASE "{template}"')
        finally:
            await admin.close()
        write_env_file_for_database(env_file, template_env, template_dsn)
        _run_npm("db:e2e:migrate", template_env)
        _run_npm("db:e2e:seed", template_env)
        await _stamp_stand(template_dsn, route_rules)
        print(f"[e2e-db] шаблон {template}: собран за {time.monotonic() - started:.1f}s")
    else:
        print(f"[e2e-db] шаблон {template}: совпадает с репозиторием (head {repo_head}) — не трогаю")

    if not template_env.exists():
        write_env_file_for_database(env_file, template_env, template_dsn)

    # По клону на воркера (#289). Внутри одного прогона воркеры Playwright
    # делят один клон, а `apiResetAll()` — `TRUNCATE … CASCADE` по таблицам:
    # соседний воркер сносил данные mid-flight. Раздельные клоны это снимают.
    # При `workers == 1` клон и env-файл остаются прежними (без суффикса).
    worker_ids: list[int | None] = list(range(workers)) if workers > 1 else [None]
    run_dbs: list[str] = []
    run_envs: list[Path] = []
    started = time.monotonic()
    for worker in worker_ids:
        run_db = run_db_name(base, run_id, worker=worker)
        await _clone_database(dsn, run_db, template)
        run_env = env_file.parent / run_env_file_name(run_id, worker)
        write_env_file_for_database(env_file, run_env, dsn_with_database(dsn, run_db))
        run_dbs.append(run_db)
        run_envs.append(run_env)
    clone_took = time.monotonic() - started

    dropped = await _drop_stale_runs(
        dsn,
        base,
        older_than_minutes=stale_run_minutes,
        env_dir=env_file.parent,
        keep=set(run_dbs),
    )
    for name in dropped:
        print(f"[e2e-db] брошенный клон {name}: снесён (> {stale_run_minutes} мин)")

    for run_db, run_env in zip(run_dbs, run_envs):
        print(f"[e2e-db] клон прогона {run_db}: готов")
    print(f"[e2e-db] клоны прогона ({len(run_dbs)}): готовы за {clone_took:.1f}s")
    # Первый env-файл — прежним ключом: одиночный прогон и отладка его ждут.
    print(f"E2E_RUN_ENV_FILE={run_envs[0]}")
    # Все — новым: по ним `run-e2e.mjs` поднимает backend на каждый воркер.
    print(f"E2E_RUN_ENV_FILES={json.dumps([str(p) for p in run_envs])}")
    print(f"E2E_RUN_DBS={json.dumps(run_dbs)}")
    print(f"E2E_RUN_DB={run_dbs[0]}")
    return 0


async def _drop_stale_runs(
    dsn: str,
    base: str,
    *,
    older_than_minutes: int,
    env_dir: Path,
    keep: set[str] | None = None,
) -> list[str]:
    """Снести клоны `«<база>_run_<stamp>_…»`, старше N минут (по метке в имени)."""
    if older_than_minutes <= 0:
        return []
    admin = await _admin_connection(dsn)
    dropped: list[str] = []
    try:
        names = [
            row["datname"]
            for row in await admin.fetch(
                "SELECT datname FROM pg_database WHERE datname LIKE $1", f"{base}{RUN_INFIX}%"
            )
        ]
        for name in names:
            if keep is not None and name in keep:
                continue
            stamp = name[len(base) + len(RUN_INFIX) :].split("_", 1)[0]
            try:
                created = datetime.strptime(stamp, RUN_STAMP_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                continue  # имя не наше — руками трогать не будем
            age_minutes = (datetime.now(tz=UTC) - created).total_seconds() / 60
            if age_minutes <= older_than_minutes:
                continue
            await _drop_database(admin, name)
            dropped.append(name)
            # Имя клона: `<база>_run_<stamp>_<run-id>[_w<номер>]`, а env-файл —
            # по run-id и тому же суффиксу воркера (#289).
            tail = name[len(base) + len(RUN_INFIX) :].split("_", 1)
            run_id_part = tail[1].removesuffix("_") if len(tail) > 1 else ""
            worker = split_worker_suffix(name, base, run_id_part)
            (env_dir / run_env_file_name(run_id_part, worker)).unlink(missing_ok=True)
    finally:
        await admin.close()
    return dropped


async def drop_runs(
    *,
    env_file: Path,
    run_id: str | None,
    stale_run_minutes: int = DEFAULT_STALE_RUN_MINUTES,
) -> int:
    """Удалить клон прогона и/или клоны брошенных прогонов."""
    dsn = resolve_stand_dsn(env_file)
    base = _db_name(dsn)
    if not run_id and stale_run_minutes <= 0:
        raise StandRunError("нечего удалять: нужен --run-id и/или --stale-run-minutes > 0")

    admin = await _admin_connection(dsn)
    try:
        if run_id:
            checked = validate_run_id(run_id)
            # Метка времени в имени — от старта прогона, а не от момента drop,
            # поэтому точное имя не восстанавливается: ищем по run-id.
            #
            # Два шаблона, а не один: клон без суффикса оканчивается на
            # `<run-id>`, а воркерный — на `<run-id>_w<N>` (#289). Один шаблон
            # `%_<run-id>` воркерные клоны не ловил **никогда**, и `drop`
            # молча рапортовал об успехе, ничего не удалив.
            names = sorted(
                {
                    row["datname"]
                    for pattern in (
                        f"{base}{RUN_INFIX}%_{checked}",
                        f"{base}{RUN_INFIX}%_{checked}{WORKER_SUFFIX}%",
                    )
                    for row in await admin.fetch(
                        "SELECT datname FROM pg_database WHERE datname LIKE $1",
                        pattern,
                    )
                }
            )
            if not names:
                print(f"[e2e-db] клон прогона {checked}: не найден (уже удалён?)")
            for found in names:
                await _drop_database(admin, found)
                worker = split_worker_suffix(found, base, checked)
                (env_file.parent / run_env_file_name(checked, worker)).unlink(missing_ok=True)
                print(f"[e2e-db] клон {found}: удалён")
    finally:
        await admin.close()

    for name in await _drop_stale_runs(
        dsn,
        base,
        older_than_minutes=stale_run_minutes,
        env_dir=env_file.parent,
        keep=None,
    ):
        print(f"[e2e-db] брошенный клон {name}: снесён (> {stale_run_minutes} мин)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка БД E2E-стенда")
    parser.add_argument("command", choices=["ensure", "prep", "drop"])
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
    parser.add_argument(
        "--run-id",
        default=os.environ.get("E2E_RUN_ID"),
        help="id клона прогона (prep/drop; по умолчанию — E2E_RUN_ID)",
    )
    parser.add_argument(
        "--keep-template",
        action="store_true",
        default=os.environ.get("E2E_TEMPLATE_KEEP") == "1",
        help="не пересобирать расходящийся шаблон (то же — E2E_TEMPLATE_KEEP=1)",
    )
    parser.add_argument(
        "--stale-run-minutes",
        type=int,
        default=int(os.environ.get("E2E_STALE_RUN_MINUTES", DEFAULT_STALE_RUN_MINUTES)),
        help="возраст, после которого клон брошенного прогона сносится",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("E2E_WORKERS", "1")),
        help="сколько воркеров Playwright в прогоне: столько же клонов БД (#289)",
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
        if args.command == "ensure":
            asyncio.run(ensure_database(dsn, keep=args.keep))
            return 0
        if args.command == "prep":
            return asyncio.run(
                prepare_run(
                    validate_run_id(args.run_id),
                    env_file=args.env_file,
                    keep_template=args.keep_template,
                    stale_run_minutes=args.stale_run_minutes,
                    workers=max(1, args.workers),
                )
            )
        return asyncio.run(
            drop_runs(
                env_file=args.env_file,
                run_id=args.run_id,
                stale_run_minutes=args.stale_run_minutes,
            )
        )
    except Exception as exc:  # noqa: BLE001 — CLI: причина попадает в сообщение
        print(f"[e2e-db] не удалось подготовить БД стенда: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
