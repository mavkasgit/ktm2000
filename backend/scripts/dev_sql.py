#!/usr/bin/env python
"""Выполнить SQL на БД приложения (по умолчанию dev-БД).

    npm run db:sql -- "select count(*) from products"
    npm run db:sql -- -f query.sql
    npm run db:sql -- "update product_1c_skipped set note = '…' where code = '11820'"

DSN берётся из env-файла (`.env.dev`; `$ENV_FILE` — явно другой стенд), как у
приложения, а не из переменной окружения. Одна команда за вызов: SELECT
печатает строки (по умолчанию до 200, `--max-rows`), DML/DDL коммитится.

Правки данных dev-БД делаются так, а миграции — под схему и прод, где нужны
версии «до/после». Прод-стенд (`ENV=prod`) требует явного `--allow-prod`.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

PROD_ENVS = {"prod", "production"}
DEFAULT_MAX_ROWS = 200


def _assert_not_production(allow_prod: bool) -> None:
    if allow_prod:
        return
    env = os.environ.get("ENV", "dev").strip().lower()
    if env in PROD_ENVS:
        raise SystemExit(
            f"db:sql отказан: окружение ENV={env}. Для dev-данных это верный "
            "путь, для прода — миграция или осознанный --allow-prod."
        )


def _print_target() -> None:
    from sqlalchemy.engine import make_url

    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        return
    url = make_url(raw)
    env = os.environ.get("ENV", "dev").strip() or "dev"
    print(f"-- ENV={env} {url.host}:{url.port}/{url.database}")


async def _run(sql: str, max_rows: int) -> int:
    from app.core.database import engine
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            if result.returns_rows:
                keys = list(result.keys())
                rows = result.fetchmany(max_rows + 1)
                print(" | ".join(keys))
                for row in rows[:max_rows]:
                    print(" | ".join("NULL" if value is None else str(value) for value in row))
                if len(rows) > max_rows:
                    print(f"-- показано {max_rows} строк; увеличьте --max-rows")
                else:
                    print(f"-- строк: {len(rows)}")
            else:
                print(f"-- затронуто строк: {result.rowcount}")
    except SQLAlchemyError as exc:
        print(f"db:sql ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SQL на БД приложения (dev по умолчанию): одна команда за вызов.",
    )
    parser.add_argument("sql", nargs="*", help="SQL одной командой")
    parser.add_argument("-f", "--file", help="файл с SQL")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help=f"сколько строк печатать (по умолчанию {DEFAULT_MAX_ROWS})",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help="разрешить запуск при ENV=prod (осознанно)",
    )
    args = parser.parse_args()

    if args.file:
        sql = Path(args.file).read_text(encoding="utf-8")
    elif args.sql:
        sql = " ".join(args.sql)
    else:
        parser.error("передайте SQL аргументом или через --file")
    if not sql.strip():
        parser.error("пустой SQL")

    from app.core.env_file import apply_env_file

    apply_env_file(override=True)
    _assert_not_production(args.allow_prod)
    _print_target()
    return asyncio.run(_run(sql, max(1, args.max_rows)))


if __name__ == "__main__":
    raise SystemExit(main())
