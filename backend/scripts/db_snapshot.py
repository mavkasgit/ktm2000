#!/usr/bin/env python
"""Снапшот dev-БД: ``dump`` — снять слепок, ``restore`` — вернуть его.

Слепок снимается ``pg_dump`` внутри dev-контейнера и кладётся в
``data/backups/snapshots`` (вне git, тем же корнем хранения, что и бэкапы
приложения, ADR-0026). Внутри — полный дамп: справочники + оперативка, то есть
ровно то состояние, которое нужно для ручного покликивания по «Участкам».

    npm run db:snapshot -- dump demo-packing
    npm run db:snapshot -- restore demo-packing-20260926-214516

Прод-окружение запрещено: ``restore`` пересобирает базу целиком, а ``dump``
читает её целиком. Проверка идёт по ``ENV`` из ``.env.dev`` и из окружения
процесса — переменная процесса может переопределить файл.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env.dev"
SNAPSHOT_DIR = ROOT / "data" / "backups" / "snapshots"
PROD_ENVS = {"prod", "production"}
USAGE = "Использование: db_snapshot.py dump <label> | restore <name>"


def _env_value(name: str, default: str = "") -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            match = re.match(rf"^{name}=(.*)$", line.strip())
            if match:
                return match.group(1).strip().strip('"')
    return default


def _assert_not_production(action: str) -> None:
    """Fail-fast в проде: и дамп, и restore бьют по всей базе."""
    sources = {
        f"{ENV_FILE.name}": _env_value("ENV", "dev"),
        "окружение процесса": os.environ.get("ENV", ""),
    }
    for origin, value in sources.items():
        if value.strip().lower() in PROD_ENVS:
            raise SystemExit(
                f"`db_snapshot {action}` запрещён: {origin} объявляет ENV={value}. "
                "Дамп и восстановление работают по всей базе — только dev/test."
            )


def _container() -> str:
    return _env_value("POSTGRES_CONTAINER_NAME", "ktm2000-postgres")


def _credentials() -> tuple[str, str]:
    return _env_value("POSTGRES_USER", "postgres"), _env_value("POSTGRES_DB", "ktm2000_dev")


def dump(label: str) -> Path:
    """Снять слепок БД в `data/backups/snapshots/<label>-<timestamp>.sql`."""
    _assert_not_production("dump")
    # Локальное время — осознанно: snapshots — dev-артефакт, имя читает человек
    # в своём поясе, файлы не сортируются по имени (порядок задаёт label).
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005
    name = f"{label}-{stamp}"
    user, database = _credentials()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOT_DIR / f"{name}.sql"
    result = subprocess.run(
        [
            "docker", "exec", _container(),
            "pg_dump",
            "-U", user,
            "-d", database,
            "--clean", "--if-exists", "--no-owner",
        ],
        check=True,
        capture_output=True,
    )
    target.write_bytes(result.stdout)
    (SNAPSHOT_DIR / f"{name}.meta.txt").write_text(
        "\n".join(
            [
                f"name={name}",
                f"label={label}",
                f"created_at={datetime.now().isoformat(timespec='seconds')}",  # noqa: DTZ005 — см. комментарий в dump()
                f"database={database}",
                f"container={_container()}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Снапшот сохранён: {target} ({target.stat().st_size // 1024} КБ)")
    return target


def restore(name: str) -> None:
    """Залить слепок обратно в dev-БД (база сносится и собирается заново)."""
    _assert_not_production("restore")
    source = SNAPSHOT_DIR / f"{name}.sql"
    if not source.exists():
        available = ", ".join(sorted(path.stem for path in SNAPSHOT_DIR.glob("*.sql"))) or "—"
        raise SystemExit(f"Снапшот {name} не найден. Доступны: {available}")
    user, database = _credentials()
    with source.open("rb") as stream:
        subprocess.run(
            [
                "docker", "exec", "-i", _container(),
                "psql", "-v", "ON_ERROR_STOP=1",
                "-U", user, "-d", database,
            ],
            check=True,
            stdin=stream,
        )
    print(f"Снапшот {name} восстановлен в БД {database}")


def main() -> None:
    command, *rest = sys.argv[1:]
    if not rest:
        raise SystemExit(USAGE)
    if command == "dump":
        dump(rest[0])
    elif command == "restore":
        restore(rest[0])
    else:
        raise SystemExit(USAGE)


if __name__ == "__main__":
    main()
