#!/usr/bin/env python
"""Собрать страницу «Изображения каталога» (#463) или только проверить её источники.

  python scripts/build-visual-review.py            # data/reviews/visual-review.html
  python scripts/build-visual-review.py --check    # расхождения, exit 1, без HTML

Страница — артефакт генератора: меняется `docs/catalog/visual-truth.csv`, storage
или карточка в БД, затем страница пересобирается. Руками HTML не правят.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviews import cli, common, visual


def main() -> int:
    args = cli.parser("HTML-обзор изображений каталога").parse_args()

    products = common.load_products()
    truth, duplicates = common.load_truth()
    register = common.load_register()

    if duplicates:
        print(f"! visual-truth.csv: повторяющиеся артикулы — {', '.join(duplicates)}")
    found = visual.problems(products, truth, register)
    kinds = Counter(row.get("kind", "") for row in truth.values())
    print(
        f"артикулов: {len(truth)}; "
        + ", ".join(
            f"{common.KIND_LABELS.get(kind, kind)} {kinds.get(kind, 0)}" for kind in common.KIND_ORDER
        )
        + f"; расхождений {len(found)}"
    )
    cli.show_problems(found)

    if args.check:
        return cli.verdict(found)

    stats = visual.write(args.out, products, truth, register, found)
    cli.written(args.out, stats)
    print(f"готово: {args.out / stats['file']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
