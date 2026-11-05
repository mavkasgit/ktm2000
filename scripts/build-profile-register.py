#!/usr/bin/env python
"""Собрать реестр профилей KTM из прод-БД и аудита 2026-11-05.

Документ — единственная точка входа по данным каталога:
  docs/catalog/ktm-profile-register.md   — человекочитаемый реестр
  docs/catalog/ktm-profile-register.csv  — плоская таблица (Excel)
  docs/catalog/ktm-profile-register.json — полные данные для машин
  docs/catalog/ktm-profile-register.meta.json — ручные решения/семейства/связи

Запуск:
  python scripts/build-profile-register.py
  python scripts/build-profile-register.py --check   # только проверка свежести

Требуется доступный контейнер прод-БД (по умолчанию ktm2000-postgres-prod).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "catalog"
AUDIT = ROOT / "data" / "tmp" / "poster-photos" / "audit"
STORAGE_ROOT = ROOT / "data" / "storage-prod"
META_PATH = DOCS / "ktm-profile-register.meta.json"
MD_PATH = DOCS / "ktm-profile-register.md"
CSV_PATH = DOCS / "ktm-profile-register.csv"
JSON_PATH = DOCS / "ktm-profile-register.json"
REL_PATH = DOCS / "ktm-profile-register.relations.csv"
FAM_PATH = DOCS / "ktm-profile-register.families.csv"

CONTAINER = os.environ.get("KTM_PROD_CONTAINER", "ktm2000-postgres-prod")
DB_USER = os.environ.get("KTM_PROD_USER", "ktm2000_user")
DB_NAME = os.environ.get("KTM_PROD_DB", "ktm2000_prod")

GROUPS = {
    "01-thresholds": "Пороги и переходные профили",
    "02-corners": "Углы, уголки, ступени, кабельники",
    "03-tile": "Профили для керамической плитки и примыкающие",
    "04-plinths": "Плинтусы: алюминиевые, микро, потайные",
    "05-wall-panels": "Профили для стеновых панелей (РП-АКП, РП-СП)",
    "06-joints-kants": "Стыки, канты, накладки, вставки, швеллер, полоса",
    "07-tubes-variants": "Трубы и варианты П/У/ПТ/Ш",
    "08-unknown-missing": "Неопознанные и без фото",
}

GROUP_PROFILE = {
    "01-thresholds": "threshold",
    "02-corners": "corner",
    "03-tile": "tile_trim",
    "04-plinths": "plinth",
    "05-wall-panels": "wall_panel_profile",
    "06-joints-kants": "joint",
    "07-tubes-variants": "unknown",
    "08-unknown-missing": "unknown",
}

PROFILE_LABELS = {
    "threshold": "порог",
    "threshold_flat": "плоский порог",
    "threshold_curved": "изогнутый порог",
    "threshold_renovation": "ремонтный порог",
    "corner": "угол / уголок",
    "corner_step": "уголок на ступень",
    "corner_capillary": "капельник",
    "tile_trim": "профиль для плитки",
    "tile_insert": "вставка для плитки",
    "tile_transition": "переход для плитки",
    "gost_profile": "профиль ГОСТ",
    "plinth": "плинтус",
    "plinth_micro": "микроплинтус",
    "plinth_hidden": "потайной плинтус",
    "wall_panel_profile": "профиль стеновой панели",
    "joint": "стык / соединитель",
    "joint_t": "Т-образный стык",
    "joint_dowel": "стык с дюбелем",
    "kant": "кант",
    "overlay": "накладка",
    "insert": "вставка",
    "channel": "швеллер",
    "strip": "полоса",
    "tube": "круглая труба",
    "sheet": "лист",
    "unknown": "не определено",
}

SHAPE_LABELS = {
    "L": "L",
    "U": "U",
    "T": "T",
    "Y": "Y",
    "flat": "плоский",
    "curved": "изогнутый",
    "tube": "труба",
    "complex": "сложный",
    "sheet": "лист",
    "unknown": "?",
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def psql_json(sql: str):
    result = subprocess.run(
        [
            "docker", "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
            "-A", "-t", "-c", sql,
        ],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "psql failed")
    text = result.stdout.strip()
    return json.loads(text) if text else []


def load_db() -> tuple[list[dict], list[dict]]:
    sql = """
    select coalesce(json_agg(row_to_json(t) order by t.id), '[]'::json)
    from (
      select
        p.id, p.sku, p.code, p.name, p.type::text as type, p.unit,
        p.is_active, p.is_catalog_item, p.profile_type, p.alloy, p.color,
        p.anod_type, p.dimension_state::text as dimension_state,
        p.aliases, p.attributes, p.photo_full, p.photo_thumb, p.source, p.notes,
        coalesce((
          select json_agg(json_build_object(
            'length_mm', l.length_mm,
            'raw_length_mm', l.raw_length_mm,
            'is_primary', l.is_primary
          ) order by l.length_mm)
          from product_lengths l where l.product_id = p.id
        ), '[]'::json) as lengths,
        coalesce((
          select json_agg(json_build_object(
            'dimension_type_id', pd.dimension_type_id,
            'is_required', pd.is_required,
            'default_value', pd.default_value
          ) order by pd.dimension_type_id)
          from product_dimensions pd where pd.product_id = p.id
        ), '[]'::json) as dimensions,
        coalesce((
          select json_agg(json_build_object('code', f.code, 'name', f.name) order by f.code)
          from product_processing_flags ppf
          join processing_flags f on f.id = ppf.flag_id
          where ppf.product_id = p.id
        ), '[]'::json) as processing_flags,
        coalesce((
          select json_agg(json_build_object(
            'sku', cp.sku, 'name', cp.name,
            'quantity', pc.quantity, 'unit', pc.unit
          ) order by cp.sku)
          from product_compositions pc
          join products cp on cp.id = pc.component_product_id
          where pc.product_id = p.id
        ), '[]'::json) as composition
      from products p
    ) t;
    """
    products = psql_json(sql)
    pairs_sql = """
    select coalesce(json_agg(json_build_object(
      'a', a.sku, 'b', b.sku, 'quantity_per_hanger', pp.quantity_per_hanger
    ) order by a.sku, b.sku), '[]'::json)
    from product_pairs pp
    join products a on a.id = pp.product_a_id
    join products b on b.id = pp.product_b_id;
    """
    pairs = psql_json(pairs_sql)
    return products, pairs


def image_size(path: Path) -> tuple[int, int] | None:
    """Размер JPEG/PNG без внешних зависимостей."""
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = struct.unpack(">II", head[16:24])
                return int(width), int(height)
            if head[:2] != b"\xff\xd8":
                return None
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2:
                    return None
                if marker[0] != 0xFF:
                    return None
                code = marker[1]
                if code in {0xD8, 0xD9}:
                    continue
                length_bytes = fh.read(2)
                if len(length_bytes) < 2:
                    return None
                length = struct.unpack(">H", length_bytes)[0]
                if code in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    fh.read(1)
                    height, width = struct.unpack(">HH", fh.read(4))
                    return int(width), int(height)
                fh.seek(length - 2, 1)
    except OSError:
        return None


def parse_aliases(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def series_of(sku: str) -> str:
    if sku.startswith("Кр.труба"):
        return "Кр.труба"
    for prefix in ("ЮП-", "АТ-", "ALS-", "ПТ", "ПП", "ПС", "МС", "КП-", "Ш-"):
        if sku.startswith(prefix):
            return prefix.rstrip("-")
    if re.match(r"^П\d", sku):
        return "П"
    if re.match(r"^У\d", sku):
        return "У"
    if re.match(r"^\d", sku):
        return "KTM"
    return "other"


def parse_size_from_name(sku: str, name: str) -> str:
    text = name.replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[*x×]\s*(\d+(?:\.\d+)?)", text)
    if match:
        return f"{match.group(1)}×{match.group(2)}"
    match = re.search(r"Кр\.труба\s*(\d+(?:\.\d+)?)", text) or re.search(
        r"[ØD]\s*(\d+(?:\.\d+)?)", text
    )
    if match:
        return f"Ø{match.group(1)}"
    match = re.search(r"SSZ-(\d+(?:\.\d+)?)", text)
    if match:
        return f"SSZ-{match.group(1)}"
    if re.fullmatch(r"\d{4}", sku) and sku in {"1010", "1212", "1515", "2020", "2525", "4040"}:
        return f"{sku[:2]}×{sku[2:]}"
    if re.fullmatch(r"У\d{4}", sku):
        return f"{sku[1:3]}×{sku[3:5]}"
    match = re.search(r"(\d+(?:\.\d+)?)\s*мм", text)
    if match:
        return match.group(1)
    if sku in {"60", "80", "95", "10"}:
        return sku
    return ""


def profile_type_of(sku: str, name: str, group: str, overrides: dict) -> str:
    if sku in overrides and overrides[sku].get("profile_type"):
        return overrides[sku]["profile_type"]
    low = name.lower()
    if "накладка" in low:
        return "overlay"
    if "вставка" in low:
        return "insert"
    if "швеллер" in low:
        return "channel"
    if "полоса" in low:
        return "strip"
    if "труба" in low:
        return "tube"
    if "кант" in low:
        return "kant"
    if "микроплинтус" in low:
        return "plinth_micro"
    if "потайной" in low and "плинтус" in low:
        return "plinth_hidden"
    if "плинтус" in low:
        return "plinth"
    if "капельник" in low:
        return "corner_capillary"
    if "ступен" in low:
        return "corner_step"
    if "угол" in low or "уголок" in low:
        return "corner"
    if "стык" in low:
        return "joint_t" if "т-образ" in low else "joint"
    if "порож" in low:
        return "threshold"
    if "профиль" in low and ("стенов" in low or "рп-" in low):
        return "wall_panel_profile"
    if "гост" in low:
        return "gost_profile"
    return GROUP_PROFILE.get(group, "unknown")


def shape_of(profile_type: str, name: str, overrides: dict, sku: str) -> str:
    if sku in overrides and overrides[sku].get("shape"):
        return overrides[sku]["shape"]
    low = name.lower()
    if profile_type == "tube":
        return "tube"
    if "т-образ" in low:
        return "T"
    if profile_type in {"corner", "corner_step", "tile_trim", "corner_capillary", "kant"}:
        return "L"
    if profile_type in {"threshold", "strip", "overlay", "joint"}:
        return "flat"
    if profile_type in {"plinth", "plinth_micro", "plinth_hidden", "wall_panel_profile"}:
        return "complex"
    if profile_type == "channel":
        return "U"
    return "unknown"


def material_of(name: str, alloy: str | None) -> str:
    low = (name or "").lower()
    if alloy:
        return alloy
    if "алюмин" in low:
        return "алюминий"
    if "нержав" in low:
        return "нержавейка"
    if "латун" in low:
        return "латунь"
    if "сталь" in low:
        return "сталь"
    return "—"


def fmt_value(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    return str(value)


def fmt_p(value, source: str) -> str:
    if value is None or value == "":
        return "—"
    return f"{fmt_value(value)} ({source})" if source else fmt_value(value)


def relation_key(left: str, right: str) -> str:
    return "|".join(sorted([left, right]))


def build():
    products, pairs = load_db()
    by_sku = {item["sku"]: item for item in products}
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    overrides = meta.get("classification", {})
    fam_defs = meta.get("families", [])
    alias_notes = meta.get("alias_notes", {})
    visual_similar = meta.get("visual_similar", [])
    deleted = meta.get("deleted", [])
    manual_claims = meta.get("claims", {})

    group_rows: dict[str, dict] = {}
    for path in sorted((AUDIT / "groups").glob("*/results.csv")):
        for row in read_csv(path):
            row["_group"] = path.parent.name
            group_rows[row["sku"]] = row
    dims = {row["sku"]: row for row in read_csv(AUDIT / "dimensions" / "dimensions-reconciled.csv")}
    decisions = {row["sku"]: row for row in read_csv(AUDIT / "decisions-applied.csv")}
    applied_photo = set(meta.get("photo_applied", []))

    # fingerprint of DB data (not audit)
    canonical = json.dumps(products, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    # families
    family_rows = []
    family_membership = defaultdict(list)
    for family in fam_defs:
        present = [sku for sku in family.get("members", []) if sku in by_sku]
        if not present:
            continue
        family_rows.append({**family, "members": present})
        for sku in present:
            family_membership[sku].append(family["id"])
    primary_family = {}
    for sku in by_sku:
        families = family_membership.get(sku, [])
        preferred = [fam for fam in families if fam.startswith(("tile_", "threshold_", "corner_", "y_", "t_joint_", "kant_", "floor_", "edge_"))]
        primary_family[sku] = (preferred or families or [None])[0]

    # alias groups
    graph = defaultdict(set)
    for item in products:
        for alias in parse_aliases(item.get("aliases")):
            if alias in by_sku:
                graph[item["sku"]].add(alias)
                graph[alias].add(item["sku"])
    seen = set()
    components = []
    for sku in by_sku:
        if sku in seen:
            continue
        stack = [sku]
        seen.add(sku)
        component = set()
        while stack:
            current = stack.pop()
            component.add(current)
            for neighbor in graph.get(current, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(component)

    # relations
    relation_rows = []
    relation_index = set()

    def add_relation(left, right, relation, status, source, note):
        if left == right or left not in by_sku or right not in by_sku:
            return
        key = (left, relation, right)
        if key in relation_index:
            return
        relation_index.add(key)
        relation_rows.append({
            "from_sku": left, "relation": relation, "to_sku": right,
            "status": status, "source": source, "note": note,
        })

    alias_pairs = set()
    for component in components:
        members = sorted(component)
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                alias_pairs.add((left, right))
    for left, right in sorted(alias_pairs):
        note = alias_notes.get(relation_key(left, right), "DB-алиас: тот же товар под другим кодом")
        status = "confirmed"
        if any(key in alias_notes for key in (f"{left}|{right}", f"{right}|{left}")):
            status = "confirmed"
        add_relation(left, right, "alias_of", status, "db:aliases", note)
        add_relation(right, left, "alias_of", status, "db:aliases", note)

    for pair in visual_similar:
        left, right = pair["a"], pair["b"]
        add_relation(left, right, "visual_similar", "confirmed", "manual:audit", pair["note"])
        add_relation(right, left, "visual_similar", "confirmed", "manual:audit", pair["note"])

    for pair in pairs:
        left, right = pair["a"], pair["b"]
        note = f"пара для фасовки, N={fmt_value(pair.get('quantity_per_hanger'))}"
        add_relation(left, right, "pair_with", "confirmed", "db:product_pairs", note)
        add_relation(right, left, "pair_with", "confirmed", "db:product_pairs", note)

    # shared 2024 cells from group results
    rect_to_skus = defaultdict(set)
    for sku, row in group_rows.items():
        for chunk in (row.get("cells_2024") or "").split(" | "):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                rect = tuple(int(float(part)) for part in chunk.split(","))
            except ValueError:
                continue
            rect_to_skus[rect].add(sku)
    for rect, skus in rect_to_skus.items():
        members = sorted(skus)
        if len(members) < 2:
            continue
        note = "ячейка 2024 " + ",".join(str(value) for value in rect)
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                add_relation(left, right, "shared_cell_2024", "confirmed", "poster2024", note)
                add_relation(right, left, "shared_cell_2024", "confirmed", "poster2024", note)

    # shared photo files
    full_hashes = defaultdict(list)
    thumb_hashes = defaultdict(list)
    for sku, item in by_sku.items():
        full = item.get("photo_full")
        thumb = item.get("photo_thumb")
        if full and (STORAGE_ROOT / full).is_file():
            full_hashes[hashlib.sha256((STORAGE_ROOT / full).read_bytes()).hexdigest()].append(sku)
        if thumb and (STORAGE_ROOT / thumb).is_file():
            thumb_hashes[hashlib.sha256((STORAGE_ROOT / thumb).read_bytes()).hexdigest()].append(sku)
    for hash_value, skus in full_hashes.items():
        if len(skus) < 2:
            continue
        for i, left in enumerate(sorted(skus)):
            for right in sorted(skus)[i + 1:]:
                add_relation(left, right, "shared_photo_full", "confirmed", "storage:sha256", hash_value[:12])
                add_relation(right, left, "shared_photo_full", "confirmed", "storage:sha256", hash_value[:12])
    for hash_value, skus in thumb_hashes.items():
        if len(skus) < 2:
            continue
        for i, left in enumerate(sorted(skus)):
            for right in sorted(skus)[i + 1:]:
                add_relation(left, right, "shared_photo_thumb", "confirmed", "storage:sha256", hash_value[:12])
                add_relation(right, left, "shared_photo_thumb", "confirmed", "storage:sha256", hash_value[:12])

    relations_by_sku = defaultdict(list)
    for row in relation_rows:
        relations_by_sku[row["from_sku"]].append(row)

    # dimension confidence overrides
    dimension_conf = {
        "371": 100, "ALS-1103": 95, "ЮП-3019": 100, "3418": 90,
        "84": 100, "ЮП-045": 100, "1010": 80, "3329": 85,
        "80": 100, "031": 100, "130": 100, "ЮП-2396": 100,
        "337": 100, "ЮП-2077": 100, "347": 100, "ЮП-2183": 100,
        "ЮП-2910": 90, "ЮП-3473": 90, "325": 95,
    }
    identity_conf = {
        "371": 95, "ALS-1103": 95, "3418": 95,
        "337": 90, "ЮП-2077": 90,
        "ЮП-2910": 90, "ЮП-3473": 90, "325": 90,
    }
    photo_conf = {
        "371": 100, "ALS-1103": 95, "3418": 100, "ЮП-3019": 95,
        "84": 95, "ЮП-045": 95, "1010": 100, "3329": 95,
        "80": 95, "031": 95, "130": 95, "ЮП-2396": 95,
        "337": 100, "ЮП-2077": 95, "347": 100, "ЮП-2183": 80,
        "ЮП-2910": 95, "ЮП-3473": 95, "325": 100,
    }

    records = []
    for item in products:
        sku = item["sku"]
        group_row = group_rows.get(sku, {})
        dim = dims.get(sku, {})
        decision = decisions.get(sku, {})
        attrs = item.get("attributes") or {}
        perimeter = attrs.get("perimeter_mm")
        if perimeter is None and dim.get("perimeter_db"):
            try:
                perimeter = float(dim["perimeter_db"])
            except ValueError:
                perimeter = None
        width = attrs.get("mount_width_mm")
        hanger_mode = attrs.get("hanger_mode") or "auto"
        qph = attrs.get("quantity_per_hanger") or {}
        lengths = item.get("lengths") or []
        primary_length = next((row["length_mm"] for row in lengths if row.get("is_primary")), None)
        if primary_length is None and lengths:
            primary_length = lengths[0]["length_mm"]
        n_value = None
        if primary_length is not None:
            entry = qph.get(str(int(primary_length))) or {}
            n_value = entry.get(hanger_mode) or entry.get("manual") or entry.get("auto")

        group = group_row.get("_group") or "08-unknown-missing"
        name = item.get("name") or sku
        profile_type = profile_type_of(sku, name, group, overrides)
        shape = shape_of(profile_type, name, overrides, sku)
        series = series_of(sku)
        material = material_of(name, item.get("alloy"))
        family = primary_family.get(sku)
        size_text = dim.get("linear_best") or ""
        size_source = dim.get("source_best") or ""
        if not size_text:
            size_text = parse_size_from_name(sku, name)
            size_source = "name"

        # special applied sizes (the audit's linear_best may be an old edition)
        applied_size = {
            "371": "30×12", "ALS-1103": "39,65×12", "ЮП-3019": "24×9,8", "3418": "24×9,8",
            "84": "28,5×5,7", "ЮП-045": "31,5×7", "1010": "10×10", "3329": "25×3",
            "80": "80×3,9", "031": "80×3,9", "130": "44×4,1", "ЮП-2396": "40×4,2",
            "337": "20,18×20", "ЮП-2077": "23,1×23,1", "347": "18,5×8", "ЮП-2183": "20×10",
            "ЮП-2910": "26×8", "ЮП-3473": "26×9", "325": "26×8",
        }
        if sku in applied_size:
            size_text = applied_size[sku]
            size_source = "чертёж/решение"

        # images
        full_path = STORAGE_ROOT / (item.get("photo_full") or "")
        thumb_path = STORAGE_ROOT / (item.get("photo_thumb") or "")
        full_exists = bool(item.get("photo_full")) and full_path.is_file()
        thumb_exists = bool(item.get("photo_thumb")) and thumb_path.is_file()
        full_size = image_size(full_path) if full_exists else None
        thumb_size = image_size(thumb_path) if thumb_exists else None
        full_px = f"{full_size[0]}x{full_size[1]}" if full_size else ""
        thumb_px = f"{thumb_size[0]}x{thumb_size[1]}" if thumb_size else ""
        if not item.get("photo_full"):
            photo_status = "нет"
        elif not item.get("photo_thumb"):
            photo_status = "только full"
        elif full_exists and thumb_exists:
            photo_status = "full+thumb"
        else:
            photo_status = "файл отсутствует"

        verdict = group_row.get("verdict") or ""
        if sku in applied_photo:
            photo_verdict = "upgrade_applied"
        elif verdict in {"ideal", "no_better"}:
            photo_verdict = "verified_best"
        elif verdict in {"upgrade_full", "upgrade_thumb", "upgrade_both"}:
            photo_verdict = "upgrade_available"
        elif verdict == "decision":
            photo_verdict = "needs_decision"
        elif verdict == "wrong_photo":
            photo_verdict = "wrong"
        elif verdict == "no_source":
            photo_verdict = "no_source"
        else:
            photo_verdict = "unverified"

        # dimension status
        dim_status = dim.get("status") or ""
        if sku in decisions:
            dim_status = "applied"
        if not perimeter and not dim.get("perimeter_archive") and not dim.get("perimeter_poster"):
            dim_status = "no_data"
        archive_p = dim.get("perimeter_archive") or ""
        poster_p = dim.get("perimeter_poster") or ""
        best_p = dim.get("perimeter_best") or ""

        def _num(value):
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                return None

        current_p = _num(perimeter)
        archive_num = _num(archive_p)
        poster_num = _num(poster_p)
        p_source = "БД" if current_p is not None else ""
        if current_p is not None and archive_num is not None and abs(current_p - archive_num) <= 0.15:
            p_source = "чертёж"
        elif current_p is not None and poster_num is not None and abs(current_p - poster_num) <= 0.15:
            p_source = "плакат"
        if sku == "1010":
            p_source = "контур 10×10"
        elif sku in {"ЮП-2910", "ЮП-3473"}:
            p_source = "чертёж 325"
        elif not p_source:
            p_source = "—"

        # confidence
        if sku in identity_conf:
            identity_pct = identity_conf[sku]
        elif group == "08-unknown-missing":
            identity_pct = 80
        else:
            identity_pct = 100

        if sku in dimension_conf:
            dimension_pct = dimension_conf[sku]
        elif dim_status == "match":
            dimension_pct = 100
        elif dim_status == "db_empty":
            dimension_pct = 90
        elif dim_status == "no_archive":
            dimension_pct = 75 if perimeter is not None else 55
        elif dim_status == "no_data":
            dimension_pct = 40
        elif dim_status == "mismatch":
            dimension_pct = 65
        else:
            dimension_pct = 60

        if sku in photo_conf:
            photo_pct = photo_conf[sku]
        elif not full_exists:
            photo_pct = 0
        elif photo_verdict == "verified_best":
            photo_pct = 100
        elif photo_verdict == "upgrade_applied":
            photo_pct = 95
        elif photo_verdict == "upgrade_available":
            photo_pct = 90
        elif photo_verdict == "needs_decision":
            photo_pct = 75
        elif photo_verdict == "wrong":
            photo_pct = 45
        elif photo_verdict == "no_source":
            photo_pct = 0
        else:
            photo_pct = 80

        family_status = None
        for family_row in family_rows:
            if family_row["id"] == family:
                family_status = family_row.get("status")
                break
        if profile_type == "unknown":
            classification_pct = 55
        elif family_status == "confirmed":
            classification_pct = 100
        elif family_status == "probable":
            classification_pct = 90
        elif family_status == "inferred":
            classification_pct = 80
        elif group == "08-unknown-missing":
            classification_pct = 60
        else:
            classification_pct = 85

        overall_pct = round(
            0.35 * identity_pct + 0.30 * dimension_pct + 0.25 * photo_pct + 0.10 * classification_pct
        )
        if overall_pct >= 93:
            overall_status = "confirmed"
        elif overall_pct >= 85:
            overall_status = "probable"
        elif overall_pct >= 70:
            overall_status = "needs_review"
        else:
            overall_status = "unknown"

        # claims
        claims = list(manual_claims.get(sku, []))
        if dim.get("perimeter_archive") and dim.get("perimeter_archive") not in {"—", "-"}:
            claims.append({
                "claim": f"Периметр {fmt_value(dim.get('perimeter_archive'))} по чертежу",
                "verdict": "confirmed",
                "evidence": dim.get("archive_file") or "архив",
            })
        if dim_status == "match" and perimeter is not None:
            claims.append({
                "claim": f"Периметр {fmt_value(perimeter)} в БД",
                "verdict": "confirmed",
                "evidence": "совпадает с чертежом" if archive_p else "источник БД",
            })
        if dim_status == "mismatch" and perimeter is not None and archive_p:
            claims.append({
                "claim": f"Периметр {fmt_value(perimeter)} в БД",
                "verdict": "refuted",
                "evidence": f"чертёж {archive_p}",
            })
        if dim_status == "no_archive" and not archive_p:
            claims.append({
                "claim": "Есть архивный чертёж",
                "verdict": "open",
                "evidence": "в архиве файла нет; размер по плакату/имени",
            })
        if photo_status == "нет":
            claims.append({
                "claim": "Есть фото товара",
                "verdict": "open",
                "evidence": "файл отсутствует; источник не найден" if photo_verdict == "no_source" else "файл отсутствует",
            })
        if group_row.get("verdict") == "decision" and sku not in decisions:
            claims.append({
                "claim": "Фото/размер требуют решения",
                "verdict": "open",
                "evidence": group_row.get("note", ""),
            })
        # de-duplicate
        unique_claims = []
        seen_claims = set()
        for claim in claims:
            key = (claim.get("claim"), claim.get("verdict"))
            if key in seen_claims:
                continue
            seen_claims.add(key)
            unique_claims.append(claim)
        claims = unique_claims

        confirmed = [c for c in claims if c.get("verdict") == "confirmed"]
        refuted = [c for c in claims if c.get("verdict") == "refuted"]
        open_claims = [c for c in claims if c.get("verdict") == "open"]

        # tags
        tags = [
            f"group:{group}",
            f"profile:{profile_type}",
            f"shape:{shape}",
            f"series:{series}",
        ]
        if family:
            tags.append(f"family:{family}")
        if size_text:
            tags.append("size:" + size_text.replace(" ", ""))
        tags.append(f"photo:{photo_status.replace(' ', '_')}")
        tags.append(f"photo-verdict:{photo_verdict}")
        tags.append(f"perimeter:{p_source.lower() if p_source else 'missing'}")
        tags.append(f"confidence:{overall_pct}")
        tags.append(f"status:{overall_status}")
        for alias in parse_aliases(item.get("aliases")):
            tags.append(f"alias:{alias}")
        for relation in relations_by_sku.get(sku, []):
            if relation["relation"] in {"visual_similar", "pair_with", "shared_photo_full", "shared_photo_thumb"}:
                tags.append(f"{relation['relation']}:{relation['to_sku']}")
        if refuted:
            tags.append("refuted")
        if open_claims:
            tags.append("open")

        relation_text = "; ".join(
            f"{rel['relation']}→{rel['to_sku']}"
            for rel in relations_by_sku.get(sku, [])
            if rel["relation"] in {"alias_of", "visual_similar", "pair_with"}
        )
        family_text = family or ""
        if family:
            family_name = next((row["name"] for row in family_rows if row["id"] == family), family)
            family_text = f"{family_name} [{family}]"

        records.append({
            "id": item["id"],
            "sku": sku,
            "code": item.get("code") or "",
            "name": name,
            "type": item.get("type") or "",
            "unit": item.get("unit") or "",
            "is_active": item.get("is_active"),
            "is_catalog_item": item.get("is_catalog_item"),
            "profile_type_db": item.get("profile_type") or "",
            "alloy": item.get("alloy") or "",
            "color": item.get("color") or "",
            "anod_type": item.get("anod_type") or "",
            "dimension_state": item.get("dimension_state") or "",
            "aliases": parse_aliases(item.get("aliases")),
            "lengths": lengths,
            "length_primary_mm": primary_length,
            "perimeter_mm": perimeter,
            "mount_width_mm": width,
            "hanger_mode": hanger_mode,
            "quantity_per_hanger": qph,
            "n_per_hanger": n_value,
            "photo_full": item.get("photo_full") or "",
            "photo_thumb": item.get("photo_thumb") or "",
            "photo_full_exists": full_exists,
            "photo_thumb_exists": thumb_exists,
            "photo_full_px": full_px,
            "photo_thumb_px": thumb_px,
            "photo_full_bytes": full_path.stat().st_size if full_exists else 0,
            "photo_thumb_bytes": thumb_path.stat().st_size if thumb_exists else 0,
            "photo_full_sha12": (
                hashlib.sha256(full_path.read_bytes()).hexdigest()[:12] if full_exists else ""
            ),
            "photo_thumb_sha12": (
                hashlib.sha256(thumb_path.read_bytes()).hexdigest()[:12] if thumb_exists else ""
            ),
            "attributes_json": item.get("attributes") or {},
            "dimensions": item.get("dimensions") or [],
            "notes": item.get("notes") or "",
            "source": item.get("source") or "",
            "processing_flags": item.get("processing_flags") or [],
            "composition": item.get("composition") or [],
            "audit_group": group,
            "audit_verdict": verdict,
            "audit_confidence": group_row.get("confidence") or "",
            "audit_note": group_row.get("note") or "",
            "audit_evidence": group_row.get("evidence") or "",
            "photo_status": photo_status,
            "photo_verdict": photo_verdict,
            "perimeter_archive": archive_p,
            "perimeter_poster": poster_p,
            "perimeter_best": best_p,
            "perimeter_source": p_source,
            "dimension_status": dim_status,
            "dimension_note": (
                decision.get("decision")
                if sku in decisions and decision.get("decision")
                else (dim.get("conflict_note") or dim.get("status") or "")
            ),
            "applied_decision": decision.get("decision") or "",
            "archive_file": dim.get("archive_file") or "",
            "poster_source": dim.get("poster_source") or "",
            "linear_best": size_text,
            "linear_source": size_source,
            "classification_profile": profile_type,
            "classification_profile_label": PROFILE_LABELS.get(profile_type, profile_type),
            "classification_shape": shape,
            "classification_series": series,
            "classification_family": family or "",
            "classification_family_name": family_text,
            "material": material,
            "identity_confidence": identity_pct,
            "dimension_confidence": dimension_pct,
            "photo_confidence": photo_pct,
            "classification_confidence": classification_pct,
            "overall_confidence": overall_pct,
            "overall_status": overall_status,
            "tags": tags,
            "relations": relations_by_sku.get(sku, []),
            "relation_text": relation_text,
            "confirmed": confirmed,
            "refuted": refuted,
            "open_claims": open_claims,
        })

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "db_fingerprint": fingerprint,
        "db": {"container": CONTAINER, "database": DB_NAME, "products": len(products)},
        "meta": meta,
        "products": records,
        "relations": relation_rows,
        "families": family_rows,
        "deleted": deleted,
    }


def confidence_bucket(value: int) -> str:
    if value >= 100:
        return "100"
    if value >= 90:
        return "90–99"
    if value >= 80:
        return "80–89"
    if value >= 70:
        return "70–79"
    return "<70"


def md_escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(data: dict) -> str:
    products = data["products"]
    by_group = defaultdict(list)
    for product in products:
        by_group[product["audit_group"]].append(product)
    total = len(products)
    buckets = Counter(confidence_bucket(item["overall_confidence"]) for item in products)
    statuses = Counter(item["overall_status"] for item in products)
    with_photo = sum(1 for item in products if item["photo_status"] != "нет")
    without_photo = total - with_photo
    refuted_products = [item for item in products if item["refuted"]]
    open_products = [item for item in products if item["open_claims"]]
    confirmed_100 = [item for item in products if item["overall_confidence"] >= 100]

    lines = [
        "# Реестр профилей KTM",
        "",
        f"> Синхронизировано с прод-БД **{data['db']['database']}** "
        f"(`{data['db']['container']}`), артикулов: **{total}**.<br>",
        f"> Отпечаток БД: `{data['db_fingerprint']}`. Сгенерировано: {data['generated_at']}.<br>",
        "> Аудит фото/чертежей: 2026-11-05. Ручные решения — "
        "`docs/catalog/ktm-profile-register.meta.json`.",
        "",
        "Документ обновляется командой `npm run docs:profiles`; проверка свежести — "
        "`npm run docs:profiles:check`. Если БД изменилась, `--check` падает, пока реестр не пересобран.",
        "",
        "## Как читать уверенность",
        "",
        "Итоговая уверенность — взвешенная: идентичность 35%, размеры 30%, фото 25%, классификация 10%.",
        "",
        "| Компонент | Что означает |",
        "|---|---|",
        "| Идентичность | Совпадает ли SKU/алиас/товар с источником; 100 — подтверждено, 90 — вариант/издание, 80 — неопознанное |",
        "| Размеры | 100 — чертёж/штамп и применённое значение; 90 — чертёж с оговоркой; 80 — только плакат; 65 — конфликт; 40 — нет данных |",
        "| Фото | 100 — лучшее из доступного; 95 — заменено по аудиту; 75 — нужно решение; 0 — фото нет |",
        "| Классификация | 100 — семейство/тип подтверждены; 80–90 — вывод по группе/имени; 55 — неизвестно |",
        "",
        "Статусы: `confirmed` (≥93), `probable` (85–92), `needs_review` (70–84), `unknown` (<70).",
        "",
        "## Сводка",
        "",
        f"- Всего профилей: **{total}**; с фото: **{with_photo}**; без фото: **{without_photo}**.",
        f"- Подтверждено: **{statuses.get('confirmed', 0)}**; вероятно: **{statuses.get('probable', 0)}**; "
        f"требует проверки: **{statuses.get('needs_review', 0)}**; неизвестно: **{statuses.get('unknown', 0)}**.",
        f"- 100% уверенность: **{len(confirmed_100)}**; есть опровергнутые утверждения: **{len(refuted_products)}**; "
        f"есть открытые вопросы: **{len(open_products)}**.",
        "",
        "| Уверенность | Кол-во |",
        "|---|---:|",
    ]
    for bucket in ["100", "90–99", "80–89", "70–79", "<70"]:
        lines.append(f"| {bucket}% | {buckets.get(bucket, 0)} |")

    lines += [
        "",
        "## 100% уверенность",
        "",
    ]
    if confirmed_100:
        lines.append("Эти строки подтверждены БД, чертежом/плакатом и фото без открытых вопросов:")
        lines.append("")
        lines.append("| SKU | Название | Размер | Периметр | Фото |")
        lines.append("|---|---|---|---|---|")
        for item in sorted(confirmed_100, key=lambda row: row["sku"]):
            lines.append(
                f"| `{item['sku']}` | {md_escape(item['name'])} | {md_escape(item['linear_best'] or '—')} | "
                f"{fmt_p(item['perimeter_mm'], item['perimeter_source'])} | {item['photo_status']} |"
            )
    else:
        lines.append("Строгого 100% нет: у части карточек нет чертежа или фото. Ниже — 90–99%.")
    lines.append("")

    lines += [
        "## Таблица по группам",
        "",
        "Каждая строка — один профиль. Полные поля (включая JSON `attributes`, длины, флаги, состав) — "
        "в `ktm-profile-register.csv` и `.json`.",
        "",
    ]
    order = sorted(by_group, key=lambda key: list(GROUPS).index(key) if key in GROUPS else 99)
    for group in order:
        rows = sorted(by_group[group], key=lambda row: (row["sku"]))
        lines.append(f"### {group} — {GROUPS.get(group, group)}")
        lines.append("")
        lines.append(
            "| SKU | Название | Тип / семейство | Размер | P, мм | Ширина | Длина | N | Фото | Связи | Уверенность | Статус | Комментарий |"
        )
        lines.append("|---|---|---|---|---|---:|---:|---:|---|---|---:|---|---|")
        for item in rows:
            rel = item["relation_text"] or "—"
            comment_parts = []
            if item.get("applied_decision"):
                if item["dimension_note"]:
                    comment_parts.append(item["dimension_note"])
            else:
                if item["dimension_note"]:
                    comment_parts.append(item["dimension_note"])
                if item["audit_note"]:
                    comment_parts.append(item["audit_note"])
            if item["open_claims"]:
                comment_parts.append("Открыто: " + "; ".join(c["claim"] for c in item["open_claims"][:2]))
            comment = " / ".join(comment_parts)
            if len(comment) > 220:
                comment = comment[:217] + "…"
            lines.append(
                f"| `{item['sku']}` | {md_escape(item['name'])} | "
                f"{md_escape(PROFILE_LABELS.get(item['classification_profile'], item['classification_profile']))}"
                f"{' / ' + md_escape(item['classification_family_name']) if item['classification_family_name'] else ''} | "
                f"{md_escape(item['linear_best'] or '—')} | "
                f"{fmt_p(item['perimeter_mm'], item['perimeter_source'])} | "
                f"{fmt_value(item['mount_width_mm'])} | "
                f"{fmt_value(item['length_primary_mm'])} | "
                f"{fmt_value(item['n_per_hanger'])} | "
                f"{item['photo_status']} | {md_escape(rel)} | "
                f"**{item['overall_confidence']}%** | {item['overall_status']} | {md_escape(comment)} |"
            )
        lines.append("")

    lines += [
        "## Опровергнутые утверждения",
        "",
        "| SKU | Что опровергнуто | Чем |",
        "|---|---|---|",
    ]
    if refuted_products:
        for item in sorted(refuted_products, key=lambda row: row["sku"]):
            for claim in item["refuted"]:
                lines.append(
                    f"| `{item['sku']}` | {md_escape(claim.get('claim', ''))} | "
                    f"{md_escape(claim.get('evidence', ''))} |"
                )
    else:
        lines.append("| — | — | — |")
    lines.append("")

    lines += [
        "## Открытые вопросы",
        "",
        "| SKU | Вопрос | Почему |",
        "|---|---|---|",
    ]
    if open_products:
        for item in sorted(open_products, key=lambda row: row["sku"]):
            for claim in item["open_claims"]:
                lines.append(
                    f"| `{item['sku']}` | {md_escape(claim.get('claim', ''))} | "
                    f"{md_escape(claim.get('evidence', ''))} |"
                )
    else:
        lines.append("| — | — | — |")
    lines.append("")

    lines += [
        "## Семейства и связи",
        "",
        "| Семейство | Участники | Основание | Статус |",
        "|---|---|---|---|",
    ]
    for family in data["families"]:
        lines.append(
            f"| {md_escape(family['name'])} (`{family['id']}`) | "
            f"{', '.join('`' + sku + '`' for sku in family['members'])} | "
            f"{md_escape(family['basis'])} | {family['status']} |"
        )
    lines.append("")

    lines += [
        "### Алиасы",
        "",
        "| A | B | Что это |",
        "|---|---|---|",
    ]
    alias_pairs = set()
    for relation in data["relations"]:
        if relation["relation"] == "alias_of":
            pair = tuple(sorted([relation["from_sku"], relation["to_sku"]]))
            alias_pairs.add(pair)
    for left, right in sorted(alias_pairs):
        note = next(
            (rel["note"] for rel in data["relations"]
             if rel["relation"] == "alias_of" and {rel["from_sku"], rel["to_sku"]} == {left, right}),
            "",
        )
        lines.append(f"| `{left}` | `{right}` | {md_escape(note)} |")
    lines.append("")

    lines += [
        "### Визуально похожие, но технически разные",
        "",
        "| A | B | Разница |",
        "|---|---|---|",
    ]
    visual_pairs = set()
    for relation in data["relations"]:
        if relation["relation"] == "visual_similar":
            visual_pairs.add(tuple(sorted([relation["from_sku"], relation["to_sku"]])))
    for left, right in sorted(visual_pairs):
        note = next(
            (rel["note"] for rel in data["relations"]
             if rel["relation"] == "visual_similar" and {rel["from_sku"], rel["to_sku"]} == {left, right}),
            "",
        )
        lines.append(f"| `{left}` | `{right}` | {md_escape(note)} |")
    lines.append("")

    lines += [
        "## Без фото",
        "",
    ]
    missing = [item for item in products if item["photo_status"] == "нет"]
    if missing:
        lines.append(", ".join(f"`{item['sku']}`" for item in sorted(missing, key=lambda row: row["sku"])))
    else:
        lines.append("Нет.")
    lines.append("")

    lines += [
        "## Удалённые артикулы",
        "",
        "| SKU | Почему удалён |",
        "|---|---|",
    ]
    for item in data["deleted"]:
        lines.append(f"| `{item['sku']}` | {md_escape(item['reason'])} |")
    lines.append("")

    lines += [
        "## Как обновлять",
        "",
        "```bash",
        "npm run docs:profiles          # пересобрать из прод-БД + аудита",
        "npm run docs:profiles:check    # упасть, если реестр отстал от БД",
        "```",
        "",
        "Ручные решения (семейства, алиасы, визуальные пары, опровержения) правятся в "
        "`ktm-profile-register.meta.json`; данные БД — только из прод-БД.",
        "",
        "## Файлы",
        "",
        "- `ktm-profile-register.md` — этот документ.",
        "- `ktm-profile-register.csv` — плоская таблица для Excel (все поля БД + аудит).",
        "- `ktm-profile-register.json` — полные данные и связи для машин.",
        "- `ktm-profile-register.relations.csv` — связи (алиасы, визуальные, общие фото/ячейки, пары).",
        "- `ktm-profile-register.families.csv` — семейства.",
        "- `ktm-profile-register.meta.json` — ручные решения и пояснения.",
        "",
    ]
    return "\n".join(lines)


def write_csv(data: dict) -> None:
    products = data["products"]
    fields = [
        "sku", "id", "code", "name", "type", "unit", "is_active", "is_catalog_item",
        "profile_type_db", "alloy", "color", "anod_type", "dimension_state",
        "aliases", "lengths", "length_primary_mm", "perimeter_mm", "mount_width_mm",
        "hanger_mode", "quantity_per_hanger", "n_per_hanger",
        "photo_full", "photo_thumb", "photo_full_exists", "photo_thumb_exists",
        "photo_full_px", "photo_thumb_px", "photo_full_bytes", "photo_thumb_bytes",
        "photo_full_sha12", "photo_thumb_sha12", "photo_status", "photo_verdict",
        "attributes_json", "dimensions", "notes", "source", "processing_flags", "composition",
        "audit_group", "audit_verdict", "audit_confidence", "audit_note", "audit_evidence",
        "perimeter_archive", "perimeter_poster", "perimeter_best", "perimeter_source",
        "dimension_status", "dimension_note", "applied_decision", "archive_file", "poster_source",
        "linear_best", "linear_source",
        "classification_profile", "classification_profile_label", "classification_shape",
        "classification_series", "classification_family", "classification_family_name",
        "material",
        "identity_confidence", "dimension_confidence", "photo_confidence",
        "classification_confidence", "overall_confidence", "overall_status",
        "tags", "relations", "relation_text",
        "confirmed", "refuted", "open_claims",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in products:
            row = {}
            for field in fields:
                value = item.get(field)
                if field in {"aliases", "lengths", "tags", "relations", "confirmed", "refuted", "open_claims",
                             "processing_flags", "composition", "quantity_per_hanger", "attributes_json", "dimensions"}:
                    row[field] = json.dumps(value, ensure_ascii=False)
                elif field == "relation_text":
                    row[field] = value or ""
                else:
                    row[field] = value if value is not None else ""
            writer.writerow(row)


def write_relations(data: dict) -> None:
    fields = ["from_sku", "relation", "to_sku", "status", "source", "note"]
    with REL_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(data["relations"], key=lambda row: (row["from_sku"], row["relation"], row["to_sku"])))


def write_families(data: dict) -> None:
    fields = ["id", "name", "members", "basis", "status", "kind"]
    with FAM_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for family in data["families"]:
            writer.writerow({**family, "members": ",".join(family["members"])})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="только проверить, что реестр совпадает с БД")
    args = parser.parse_args()

    if not META_PATH.exists():
        print(f"нет {META_PATH}; сначала создайте meta-файл", file=sys.stderr)
        return 2

    data = build()

    if args.check:
        if not JSON_PATH.exists():
            print("реестр ещё не собран", file=sys.stderr)
            return 1
        previous = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        if previous.get("db_fingerprint") != data["db_fingerprint"]:
            print(
                "реестр устарел: отпечаток БД изменился "
                f"({previous.get('db_fingerprint')} → {data['db_fingerprint']}). "
                "Запустите `npm run docs:profiles`.",
                file=sys.stderr,
            )
            return 1
        print(f"реестр актуален: {data['db_fingerprint']}, артикулов {len(data['products'])}")
        return 0

    DOCS.mkdir(parents=True, exist_ok=True)
    MD_PATH.write_text(render_markdown(data), encoding="utf-8")
    write_csv(data)
    write_relations(data)
    write_families(data)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {MD_PATH}")
    print(f"written {CSV_PATH}")
    print(f"written {JSON_PATH}")
    print(f"written {REL_PATH}")
    print(f"written {FAM_PATH}")
    print(f"products: {len(data['products'])}, relations: {len(data['relations'])}, families: {len(data['families'])}")
    print(f"db fingerprint: {data['db_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
