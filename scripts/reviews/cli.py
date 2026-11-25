"""Общая часть тонких точек входа: флаги, вывод расхождений, код возврата.

Точки входа (`scripts/build-visual-review.py`, `scripts/build-skipped-review.py`,
`scripts/build-catalog-reviews.py`) отличаются только тем, какие источники
зовут, — разбор аргументов и печать должны совпадать, иначе `--check` в двух
скриптах ведёт себя по-разному.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import common


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument(
        "--check",
        action="store_true",
        help="только проверить источники и расхождения, HTML не собирать",
    )
    result.add_argument(
        "--out",
        type=Path,
        default=common.OUT_DIR,
        help=f"куда писать HTML (по умолчанию {common.OUT_DIR.relative_to(common.ROOT).as_posix()})",
    )
    return result


def show_problems(found: list[dict], limit: int = 200) -> None:
    for problem in found[:limit]:
        mark = "~" if problem.get("severity") == "warn" else "!"
        print(f"  {mark} {problem['key']}: {problem['kind']} — {problem['text']}")
    if len(found) > limit:
        print(f"  … ещё {len(found) - limit}")


def errors(found: list[dict]) -> list[dict]:
    """Только то, что валит проверку: `warn` — к разбору, но не провал."""
    return [problem for problem in found if problem.get("severity") != "warn"]


def verdict(found: list[dict]) -> int:
    """`--check` для CI и хуков: расхождения — это провал, а не предупреждение."""
    blocking = errors(found)
    if blocking:
        print("ПРОВЕРКА НЕ ПРОЙДЕНА: устрани расхождения или поправь источник.")
        return 1
    if found:
        print("ПРОВЕРКА ПРОЙДЕНА, но есть замечания к разбору (не блокируют).")
    else:
        print("ПРОВЕРКА ПРОЙДЕНА.")
    return 0


def written(out: Path, stats: dict) -> None:
    path = out / stats["file"]
    print(f"  {stats['file']:<22} {path.stat().st_size / 1024:8.0f} КБ")
