#!/usr/bin/env python
"""Синк-гейт каталога: KTM (prod) -> каталог «Экранчика» (SQLite ``profiles``).

Сверяет у профилей Экранчика два поля с прод-каталогом KTM:

* ``length`` — длина профиля. Считается совпадающей, если равна любой
  нормальной длине KTM или любой её сырьевой длине (±1 мм): Экранчик
  хранит одну длину, а в KTM длина разделена на нормальную и сырьевую.
* ``quantity_per_hanger`` — норма на подвес для этой длины.

Если длина Экранчика не совпала ни с одной длиной KTM, целевой становится
основная длина KTM (primary, иначе единственная, иначе минимальная).

Имена, заметки и фото не трогаются: в Экранчике имя — это код артикула,
а заметки хранят связи «Аналог-…».

Режимы:
    python scripts/sync-ekranchik.py --check   # только проверка (по умолчанию)
    python scripts/sync-ekranchik.py --apply   # обновить БД Экранчика

Флаги: ``--db PATH`` (SQLite Экранчика), ``--json``, ``--if-enabled``
(проверка только при ``KTM_EKRANCHIK_SYNCGATE=1|true|yes|on``).

Окружение: ``EKRANCHIK_DB``, ``KTM_PG_CONTAINER`` (default
``ktm2000-postgres-prod``), ``KTM_PG_USER``, ``KTM_PG_DB``.

Коды выхода: 0 — ок, 1 — есть расхождения (в ``--check``) или ошибка
применения, 2 — неверные аргументы/окружение.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EKR_DB = ROOT.parent / "ekranchik-modern" / "static" / "ekranchik.db"

HOMO = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
    "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
})

KTM_SQL = """
select p.sku,
       coalesce(p.attributes->>'hanger_mode', 'auto'),
       coalesce(p.attributes->'quantity_per_hanger', '{}'::jsonb)::text,
       coalesce(to_jsonb(p.aliases)::text, '[]'),
       coalesce((select string_agg(pl.length_mm::text || '/' || pl.is_primary::text
                                   || '/' || coalesce(pl.raw_length_mm::text, '-'), ','
                                   order by pl.length_mm)
                 from product_lengths pl where pl.product_id = p.id), ''),
       p.is_active
from products p
order by p.sku;
"""


def canon(value: str | None) -> str:
    """Каноническая форма кода: регистр, пунктуация, латиница/кириллица."""
    text = (value or "").strip().upper().replace("Ё", "Е")
    text = re.sub(r"[^0-9A-ZА-Я]", "", text)
    text = text.translate(HOMO)
    if text.isdigit():
        text = str(int(text))
    return text


def read_ktm_catalog() -> list[dict]:
    container = os.environ.get("KTM_PG_CONTAINER", "ktm2000-postgres-prod")
    user = os.environ.get("KTM_PG_USER", "ktm2000_user")
    db = os.environ.get("KTM_PG_DB", "ktm2000_prod")
    proc = subprocess.run(
        ["docker", "exec", container, "psql", "-U", user, "-d", db,
         "-A", "-F", "\t", "--no-align", "-t", "-c", KTM_SQL],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or "psql failed")

    products = []
    for line in proc.stdout.decode("utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 6:
            continue
        sku, mode, qjson, aliases, lengths, active = fields[:6]
        qph = json.loads(qjson) if qjson.strip() else {}
        lens = []
        for chunk in lengths.split(","):
            if not chunk.strip():
                continue
            length, primary, raw = chunk.split("/")
            item = {"length": float(length), "primary": primary == "true",
                    "raw": None if raw == "-" else float(raw)}
            item["eff_raw"] = item["raw"] if item["raw"] is not None else item["length"]
            lens.append(item)
        products.append({
            "sku": sku,
            "mode": mode,
            "qph": qph,
            "aliases": json.loads(aliases or "[]"),
            "lengths": lens,
            "is_active": active == "t",
        })
    return products


def effective_n(product: dict, length: float) -> int | None:
    key = str(int(length)) if float(length).is_integer() else str(length)
    entry = product["qph"].get(key) or {}
    value = entry.get("manual") if product["mode"] == "manual" else entry.get("auto")
    if value is None:
        value = entry.get("auto" if product["mode"] == "manual" else "manual")
    return int(value) if value is not None else None


def main_length(product: dict) -> dict | None:
    lengths = product["lengths"]
    if not lengths:
        return None
    primary = [item for item in lengths if item["primary"]]
    if len(primary) == 1:
        return primary[0]
    if len(lengths) == 1:
        return lengths[0]
    return min(lengths, key=lambda item: item["length"])


def match_length(product: dict, current: float | None) -> tuple[dict | None, str | None]:
    """Длина KTM, соответствующая длине Экранчика (нормальная или сырьевая)."""
    if current is None:
        return None, None
    for item in product["lengths"]:
        if abs(item["length"] - current) <= 1:
            return item, "normal"
    for item in product["lengths"]:
        if abs(item["eff_raw"] - current) <= 1:
            return item, "raw"
    return None, None


def build_index(products: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_sku = {canon(product["sku"]): product for product in products}
    by_alias: dict[str, dict] = {}
    for product in products:
        for alias in product["aliases"]:
            by_alias.setdefault(canon(alias), product)
    return by_sku, by_alias


def read_ekr(db_path: Path) -> tuple[sqlite3.Connection, list[dict]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    rows = conn.execute(
        "select id, name, quantity_per_hanger, length from profiles order by name"
    ).fetchall()
    return conn, [
        {"id": row[0], "name": row[1], "n": row[2], "length": row[3]}
        for row in rows
    ]


def compute_drift(products: list[dict], profiles: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    by_sku, by_alias = build_index(products)
    matched_ids: set[str] = set()
    drift: list[dict] = []
    skipped: list[dict] = []

    for profile in profiles:
        key = canon(profile["name"])
        product = by_sku.get(key) or by_alias.get(key)
        if product is None:
            drift.append({"id": profile["id"], "name": profile["name"], "field": "product",
                          "old": None, "new": None, "reason": "нет в каталоге KTM"})
            continue
        matched_ids.add(canon(product["sku"]))
        if not product["lengths"]:
            skipped.append({"name": profile["name"], "ktm_sku": product["sku"],
                            "reason": "у артикула KTM нет длин"})
            continue

        item, _basis = match_length(product, profile["length"])
        if item is None:
            target = main_length(product)
            drift.append({"id": profile["id"], "name": profile["name"], "ktm_sku": product["sku"],
                          "field": "length", "old": profile["length"],
                          "new": target["length"], "reason": "нет такой длины в KTM"})
            item = target

        target_n = effective_n(product, item["length"])
        if target_n is not None and int(profile["n"] or -1) != target_n:
            drift.append({"id": profile["id"], "name": profile["name"], "ktm_sku": product["sku"],
                          "field": "quantity_per_hanger", "old": profile["n"],
                          "new": target_n, "reason": f"норма для длины {int(item['length'])}"})
        elif target_n is None and profile["n"] is not None:
            skipped.append({"name": profile["name"], "ktm_sku": product["sku"],
                            "reason": "у артикула KTM нет нормы"})

    ktm_only = sorted(p["sku"] for p in products if canon(p["sku"]) not in matched_ids)
    return drift, skipped, ktm_only


def apply_drift(db_path: Path, drift: list[dict], dry_run: bool) -> Path | None:
    fields = {"length": "length", "quantity_per_hanger": "quantity_per_hanger"}
    changes = [item for item in drift if item["field"] in fields]
    if not changes or dry_run:
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    src = sqlite3.connect(db_path, timeout=15)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    conn = sqlite3.connect(db_path, timeout=15)
    try:
        with conn:
            for item in changes:
                column = fields[item["field"]]
                conn.execute(
                    f"update profiles set {column} = ?, updated_at = ? where id = ?",
                    (item["new"], datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                     item["id"]),
                )
    finally:
        conn.close()
    return backup


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Синк-гейт каталога KTM -> Экранчик")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="только проверка (по умолчанию)")
    mode.add_argument("--apply", action="store_true", help="обновить БД Экранчика")
    parser.add_argument("--db", type=Path, default=None, help="путь к ekranchik.db")
    parser.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    parser.add_argument("--if-enabled", action="store_true",
                        help="работать только при KTM_EKRANCHIK_SYNCGATE=1|true|yes|on")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.if_enabled:
        value = os.environ.get("KTM_EKRANCHIK_SYNCGATE")
        if value is None:
            print("Синк-гейт каталога отключён (KTM_EKRANCHIK_SYNCGATE не установлен).")
            return 0
        if value.strip().lower() not in {"1", "true", "yes", "on"}:
            print(f"Недопустимое значение KTM_EKRANCHIK_SYNCGATE={value!r}.", file=sys.stderr)
            return 2

    db_path = args.db or Path(os.environ.get("EKRANCHIK_DB", DEFAULT_EKR_DB))
    if not db_path.exists():
        print(f"БД Экранчика не найдена: {db_path}", file=sys.stderr)
        return 2

    try:
        products = read_ktm_catalog()
    except (RuntimeError, FileNotFoundError) as error:
        print(f"Не удалось прочитать каталог KTM: {error}", file=sys.stderr)
        return 2

    conn, profiles = read_ekr(db_path)
    try:
        drift, skipped, ktm_only = compute_drift(products, profiles)
    finally:
        conn.close()

    applied = drift
    backup = None
    if args.apply:
        backup = apply_drift(db_path, drift, dry_run=False)
        conn, profiles = read_ekr(db_path)
        try:
            drift, skipped, ktm_only = compute_drift(products, profiles)
        finally:
            conn.close()

    if args.json:
        print(json.dumps({
            "ok": not drift,
            "checked": len(profiles),
            "applied_fields": len(applied) if backup else 0,
            "drift": drift,
            "skipped": skipped,
            "ktm_only": ktm_only,
            "backup": str(backup) if backup else None,
        }, ensure_ascii=False, indent=1))
    else:
        if args.apply and backup:
            print(f"Обновлено полей: {len(applied)}. Бэкап: {backup}")
        if drift:
            print(f"Расхождения: {len(drift)} (проверено {len(profiles)} профилей)")
            for item in drift:
                if item["field"] == "product":
                    print(f"  {item['name']}: {item['reason']}")
                else:
                    print(f"  {item['name']}: {item['field']} {item['old']} -> {item['new']} ({item['reason']})")
        else:
            print(f"Синк-гейт пройден: {len(profiles)} профилей совпадают с KTM.")
        if skipped:
            print(f"Пропущено (нет данных в KTM): {len(skipped)}")
            for item in skipped:
                print(f"  {item['name']} ({item['ktm_sku']}): {item['reason']}")
        if ktm_only:
            print(f"Артикулов только в KTM (в Экранчике нет): {len(ktm_only)}")

    return 0 if not drift else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
