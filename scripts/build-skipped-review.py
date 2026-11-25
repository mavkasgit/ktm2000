#!/usr/bin/env python
"""Собрать страницу «Реестр исключений ОСВ» (#464) или проверить реестр.

  python scripts/build-skipped-review.py            # data/reviews/skipped-review.html
  python scripts/build-skipped-review.py --check    # замечания, exit 1, без HTML

Источник — таблица `product_1c_skipped` в прод-БД; до применения миграции 088
на проде читается сид, из которого таблица наполняется. Страница — артефакт
генератора: меняется реестр, страница пересобирается.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviews import cli, common
from reviews import skipped as skipped_page


def main() -> int:
    args = cli.parser("HTML-обзор реестра исключений ОСВ").parse_args()

    products = common.load_products()
    rows, source = common.load_skipped()

    found = skipped_page.problems(rows, products)
    by_reason = {}
    for row in rows:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
    print(
        f"записей: {len(rows)} ({source}); "
        + ", ".join(f"{reason} {by_reason.get(reason, 0)}" for reason in common.REASON_ORDER)
        + f"; замечаний {len(found)}"
    )
    cli.show_problems(found)

    if args.check:
        return cli.verdict(found)

    stats = skipped_page.write(args.out, rows, source, products, found)
    cli.written(args.out, stats)
    print(f"готово: {args.out / stats['file']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
