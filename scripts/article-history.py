"""История артикула по артефактам change-set'ов (read-only).

Собирает состояния одного артикула из `data/backups/changesets/*` в
хронологическом порядке: до/после каждой правки, длины (нормальная/сырьевая/
основная), коды 1С, имя и алиасы. Полные дампы БД печатаются рядом — по ним
состояние восстанавливается, даже если построчного снимка у правки нет.

    python scripts/article-history.py "Кр.труба 10мм"
    python scripts/article-history.py 1212
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGESETS = ROOT / "data/backups/changesets"


def norm(value: object) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def sku_matches(product: dict, needle: str) -> bool:
    aliases = product.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return norm(product.get("sku")) == needle or any(
        norm(alias) == needle for alias in aliases
    )


def lengths_text(rows: list[dict]) -> str:
    if not rows:
        return "—"
    parts = []
    for row in sorted(rows, key=lambda item: float(item.get("length_mm") or 0)):
        length = row.get("length_mm")
        if length is None:
            continue
        text = f"{round(float(length))}"
        raw = row.get("raw_length_mm")
        if raw is not None:
            text += f"/сырье {round(float(raw))}"
        if row.get("is_primary"):
            text += " (осн.)"
        parts.append(text)
    return ", ".join(parts)


def state_from_rows(data: object, needle: str) -> dict | None:
    """before/after_rows.json форматов #492, #490, #493."""
    if isinstance(data, dict) and "product_lengths" in data:
        product = next(
            (item for item in data.get("products") or [] if sku_matches(item, needle)),
            None,
        )
        if product is None:
            return None
        lengths = [
            row
            for row in data.get("product_lengths") or []
            if norm(row.get("sku")) == norm(product.get("sku"))
        ]
        return {
            "name": product.get("name"),
            "aliases": product.get("aliases") or [],
            "lengths": lengths,
            "codes": [],
        }
    if isinstance(data, dict) and "products" in data:
        product = next(
            (item for item in data.get("products") or [] if sku_matches(item, needle)),
            None,
        )
        if product is None:
            return None
        pid = product.get("id")
        lengths = [
            row for row in data.get("lengths") or [] if row.get("product_id") == pid
        ]
        codes = data.get("codes") or data.get("bindings") or []
        return {
            "name": product.get("name"),
            "aliases": product.get("aliases") or [],
            "lengths": lengths,
            "codes": sorted(
                str(row.get("code"))
                for row in codes
                if row.get("product_id") == pid
            ),
        }
    if isinstance(data, list):
        rows = [
            row
            for row in data
            if norm(row.get("sku")) == needle
            or any(norm(alias) == needle for alias in row.get("aliases") or [])
        ]
        if not rows:
            return None
        row = rows[0]
        return {
            "name": row.get("name"),
            "aliases": row.get("aliases") or [],
            "lengths": [
                {
                    "length_mm": item.get("length_mm"),
                    "raw_length_mm": item.get("raw_length_mm"),
                    "is_primary": item.get("is_primary"),
                }
                for item in rows
            ],
            "codes": sorted(str(item.get("code")) for item in rows if item.get("code")),
        }
    return None


def state_from_named(data: object, needle: str) -> dict | None:
    """#469: before_dev/after_dev — dict pid → карточка."""
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, dict) and sku_matches(value, needle):
            return {
                "name": value.get("name"),
                "aliases": value.get("aliases") or [],
                "lengths": [],
                "codes": [],
                "extra": {
                    key: value.get(key)
                    for key in ("mount_width_mm", "perimeter_mm", "quantity_per_hanger")
                    if key in value
                },
            }
    return None


def state_from_codes(data: object, needle: str) -> dict | None:
    """#466: before/after.json — dict код → привязка."""
    if not isinstance(data, dict):
        return None
    codes = sorted(
        str(code)
        for code, value in data.items()
        if isinstance(value, dict) and norm(value.get("sku")) == needle
    )
    if not codes:
        return None
    return {"name": None, "aliases": [], "lengths": [], "codes": codes}


def load(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sku", help="SKU или алиас артикула")
    args = parser.parse_args()
    needle = norm(args.sku)

    entries = []
    for directory in sorted(CHANGESETS.iterdir()):
        if not directory.is_dir():
            continue
        meta_path = directory / "meta.json"
        if not meta_path.exists():
            continue
        meta = load(meta_path) or {}
        entries.append(
            (
                meta.get("started_at") or meta.get("finished_at") or "",
                directory,
                meta,
            )
        )
    entries.sort(key=lambda item: item[0])

    found = False
    for started_at, directory, meta in entries:
        sides = []
        for name, kind in [
            ("before_rows.json", "rows"),
            ("after_rows.json", "rows"),
            ("before_rows_prod.json", "rows"),
            ("after_rows_prod.json", "rows"),
            ("before_dev.json", "named"),
            ("after_dev.json", "named"),
            ("before.json", "codes"),
            ("after.json", "codes"),
        ]:
            path = directory / name
            if not path.exists():
                continue
            data = load(path)
            if kind == "rows":
                state = state_from_rows(data, needle)
            elif kind == "named":
                state = state_from_named(data, needle)
            else:
                state = state_from_codes(data, needle)
            if state is not None:
                sides.append((name, state, path))

        if not sides:
            continue
        found = True
        print(f"\n## {meta.get('label') or directory.name} — {started_at}")
        db = meta.get("db") or {}
        for key, ref in db.items():
            if isinstance(ref, dict) and ref.get("ref"):
                print(f"   дамп {key}: {ref['ref']}")
            elif isinstance(ref, str):
                print(f"   дамп {key}: {ref}")
        for name, state, path in sides:
            print(f"   {name} ({path}):")
            if state.get("name"):
                print(f"     имя: {state['name']}")
            if state.get("aliases"):
                print(f"     алиасы: {', '.join(map(str, state['aliases']))}")
            if state.get("lengths"):
                print(f"     длины: {lengths_text(state['lengths'])}")
            if state.get("codes"):
                print(f"     коды 1С: {', '.join(state['codes'])}")
            if state.get("extra"):
                print(f"     прочее: {state['extra']}")

    if not found:
        print(f"Артикул {args.sku!r} не найден в построчных артефактах change-set'ов.")
        print(f"Полные дампы: {ROOT / 'data/backups/prod'} и {ROOT / 'data/backups/snapshots'}")
        sys.exit(2)


if __name__ == "__main__":
    main()
