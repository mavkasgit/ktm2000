#!/usr/bin/env python
"""Собрать оба HTML-обзора каталога и стартовую страницу (#463, #464).

  python scripts/build-catalog-reviews.py            # всё в data/reviews/
  python scripts/build-catalog-reviews.py --check    # только проверки, exit 1
  python scripts/build-catalog-reviews.py --only=visual|skipped

Страницы собираются из источников: `docs/catalog/visual-truth.csv`, прод-БД,
storage и реестр исключений (таблица или сид). Это артефакт, а не документ:
меняется источник — страница пересобирается, руками HTML не правят.

Отдельные страницы: `build-visual-review.py`, `build-skipped-review.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviews import cli, common, index, visual
from reviews import skipped as skipped_page

CHOICES = ("all", "visual", "skipped")


def main() -> int:
    parser = cli.parser("HTML-обзоры каталога: изображения и реестр исключений ОСВ")
    parser.add_argument(
        "--only",
        choices=CHOICES,
        default="all",
        help="собрать одну страницу вместо обеих",
    )
    args = parser.parse_args()
    want_visual = args.only in ("all", "visual")
    want_skipped = args.only in ("all", "skipped")

    products = common.load_products()
    found: list[dict] = []

    visual_stats: dict = {}
    skipped_stats: dict = {}

    if want_visual:
        truth, duplicates = common.load_truth()
        register = common.load_register()
        if duplicates:
            print(f"! visual-truth.csv: повторяющиеся артикулы — {', '.join(duplicates)}")
        visual_found = visual.problems(products, truth, register)
        found.extend(visual_found)
        print(
            f"изображения: артикулов {len(truth)}, расхождений {len(visual_found)}",
        )
        cli.show_problems(visual_found)
        if not args.check:
            visual_stats = visual.write(args.out, products, truth, register, visual_found)

    if want_skipped:
        rows, source = common.load_skipped()
        skipped_found = skipped_page.problems(rows, products)
        found.extend(skipped_found)
        print(f"реестр исключений: записей {len(rows)} ({source}), замечаний {len(skipped_found)}")
        cli.show_problems(skipped_found)
        if not args.check:
            skipped_stats = skipped_page.write(args.out, rows, source, products, skipped_found)

    if args.check:
        return cli.verdict(found)

    if want_visual:
        cli.written(args.out, visual_stats)
    if want_skipped:
        cli.written(args.out, skipped_stats)
    if args.only == "all":
        path = index.write(args.out, visual_stats, skipped_stats)
        print(f"  {'index.html':<22} {path.stat().st_size / 1024:8.0f} КБ")
    print(f"готово: {args.out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
