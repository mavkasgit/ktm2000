#!/usr/bin/env python
"""Синк каталога из прод-БД KTM: «Экранчик» (SQLite) и dev-стенд.

Прод — источник правды. Скрипт доводит до него два адресата:

* **«Экранчик»** (``ekranchik.db``, таблица ``profiles``) — весь каталог:
  ``length`` (совпала с любой нормальной или сырьевой длиной KTM ±1 мм;
  иначе — основная длина KTM) и ``quantity_per_hanger`` (норма этой длины по
  ``hanger_mode``: manual → ``manual``, auto → ``auto``). Артикула нет в
  Экранчике — профиль **создаётся**: имя — код артикула KTM, длина — основная,
  норма — по режиму подвеса.
* **Фото «Экранчика»** лежат в ``static/images``. Прод — источник правды,
  поэтому фото не только заполняются в пустых полях, но и **обновляются**,
  когда меняется исходный файл KTM. Признак «фото уже это» — манифест
  ``images-sync.json`` рядом с БД: имя профиля + поле → путь и SHA-256 файла
  KTM. Пока хэш совпадает, картинка не перезаписывается (её в ЭК могли
  ужать/перекодировать); изменился файл в KTM — картинка обновляется.
  Если манифеста нет (первый запуск после обновления скрипта), занятые фото
  обновляются один раз целиком. Перед записью снимается резервная копия и
  БД, и перезаписываемых картинок.
* **Удаление профилей** по умолчанию не делается: карточка, которой нет в
  KTM, печатается как расхождение ``product``. Явный ``--prune-orphans``
  вместе с ``--apply`` удаляет такие профили и их файлы фото (после бэкапа).
  Пометки («Аналог-…») и имена существующих профилей не трогаются.

* **dev-стенд** — БД целиком и storage (``products`` + ``imports``). Dev по
  определению копия прода, поэтому переносится всё, а не только каталог:
  «изменилось в проде — поменяли и в dev». Перед восстановлением БД скрипт
  снимает снапшот (``data/backups/snapshots/pre-sync-<дата>.sql``), который
  возвращается штатным ``npm run db:snapshot -- restore <имя>``.

Режимы:
    python scripts/sync-ekranchik.py --check   # только проверка (по умолчанию)
    python scripts/sync-ekranchik.py --apply   # обновить оба адресата

Область (``--scope``): ``all`` (по умолчанию), ``ekranchik`` — только SQLite
Экранчика, ``dev`` — только dev-стенд. ``--check`` с той же областью сообщает
расхождения, ``--apply`` их устраняет.

Флаги: ``--db PATH`` (SQLite Экранчика), ``--json``, ``--if-enabled``
(проверка только при ``KTM_EKRANCHIK_SYNCGATE=1|true|yes|on``),
``--prune-orphans`` (удалять профили, которых нет в KTM; только с ``--apply``),
``--seed-manifest`` (записать текущие фото KTM в манифест, не перезаписывая
картинки; только с ``--apply``).

Окружение:
    ``EKRANCHIK_DB``       — путь к SQLite Экранчика;
    ``KTM_PG_CONTAINER``   — прод-контейнер (default ``ktm2000-postgres-prod``);
    ``KTM_PG_USER``, ``KTM_PG_DB`` — учётка и база прода;
    ``KTM_PROD_STORAGE``   — каталог storage прода (default ``data/storage-prod``).

Dev читается из ``.env.dev``: ``POSTGRES_CONTAINER_NAME``, ``POSTGRES_USER``,
``POSTGRES_DB`` и ``STORAGE_ROOT`` (путь относительно ``backend/``). Защита: при
``ENV=prod`` и при совпадении dev- и прод-контейнера dev-часть отказывает до
любой записи.

Коды выхода: 0 — ок, 1 — есть расхождения (в ``--check``) или ошибка
применения, 2 — неверные аргументы/окружение.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:  # Pillow нужен только для перекодирования PNG/WebP в JPEG.
    from PIL import Image
except ImportError:  # pragma: no cover - окружение без Pillow
    Image = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
DEV_ENV_FILE = ROOT / ".env.dev"
DEFAULT_EKR_DB = ROOT.parent / "ekranchik-modern" / "static" / "ekranchik.db"
DEFAULT_PROD_STORAGE = ROOT / "data" / "storage-prod"
PROD_ENVS = {"prod", "production"}

#: Что переносится из storage прода в dev. ``backups`` не трогаем: у dev своя
#: ротация, и дампы прод-БД в ней только путают сроки хранения.
STORAGE_SCOPES = ("products", "imports")

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
       p.is_active,
       coalesce(p.photo_thumb, ''),
       coalesce(p.photo_full, '')
from products p
order by p.sku;
"""

#: Отпечаток артикула для сверки dev с продом. Всё, что оператор видит в
#: карточке и что влияет на расчёт: идентичность, габариты и режим подвеса
#: (в ``attributes``), алиасы, длины, фото, активность. Правится каталог —
#: отпечаток меняется, и ``--check`` это называет.
PRODUCTS_SQL = """
select p.sku,
       md5(concat_ws('|',
         coalesce(p.code, ''), p.name, p.type::text, p.unit,
         p.is_active::text, coalesce(p.notes, ''),
         coalesce(p.profile_type, ''), coalesce(p.alloy, ''), coalesce(p.color, ''),
         coalesce(p.anod_type, ''), coalesce(p.photo_thumb, ''), coalesce(p.photo_full, ''),
         coalesce(p.source, ''), p.is_catalog_item::text, p.dimension_state::text,
         coalesce(to_jsonb(p.aliases)::text, '[]'),
         p.attributes::text,
         coalesce((select string_agg(pl.length_mm::text || '/' || pl.is_primary::text
                                     || '/' || coalesce(pl.raw_length_mm::text, '-'), ','
                                     order by pl.length_mm)
                   from product_lengths pl where pl.product_id = p.id), '')))
from products p
order by p.sku;
"""

#: Пары сверяются по кодам, а не по id: в dev id мог разойтись (сиды, ручные
#: вставки), и тогда совпадение последовательностей ничего не значило бы.
PAIRS_SQL = """
select a.sku || '|' || b.sku,
       md5(coalesce(pp.quantity_per_hanger::text, '{}'))
from product_pairs pp
join products a on a.id = pp.product_a_id
join products b on b.id = pp.product_b_id
order by 1;
"""

PHOTO_PATHS_SQL = """
select photo_thumb from products where photo_thumb is not null
union all
select photo_full from products where photo_full is not null
order by 1;
"""

REVISION_SQL = "select version_num from alembic_version;"


class DevSyncError(RuntimeError):
    """Dev-часть невозможна: нет .env.dev, прод-контейнер или запись запрещена."""


class PhotoSyncError(RuntimeError):
    """Фото нельзя привести к JPEG-контракту ЭК (нет Pillow, битый файл)."""


@dataclass(frozen=True)
class PgTarget:
    """Куда ходить за данными: контейнер + учётка + база."""

    container: str
    user: str
    database: str


@dataclass(frozen=True)
class DevTarget:
    """Dev-стенд: его БД и его storage (свой корень, ADR-0026)."""

    pg: PgTarget
    storage_root: Path
    env_name: str


@dataclass(frozen=True)
class PhotoTargets:
    """Куда кладутся фото Экранчика: ``static/images`` рядом с его SQLite."""

    images_dir: Path
    prod_storage: Path
    image_prefix: str = "images"

    @classmethod
    def for_db(cls, db_path: Path, prod_storage: Path) -> PhotoTargets:
        return cls(images_dir=db_path.parent / "images", prod_storage=prod_storage)


#: Пары «поле профиля → суффикс файла в ``static/images``». Имя файла — имя
#: профиля: у 144 из 191 занятых фото Экранчика правило именно такое, ещё 9 —
#: ``ALS-…`` без дефиса (их не переименовываем — файлы уже на месте).
PHOTO_FIELDS = (("photo_thumb", "-thumb.jpg"), ("photo_full", ".jpg"))

#: Манифест синка фото рядом с SQLite: имя профиля + поле → версия файла KTM.
#: Он и есть признак «картинка в ЭК соответствует этому фото KTM». Без него
#: (первый запуск) занятые фото обновляются один раз целиком.
PHOTO_MANIFEST_NAME = "images-sync.json"
PHOTO_MAX_SIDE = 1600
PHOTO_JPEG_QUALITY = 85
IMAGE_BACKUP_PREFIX = "images.bak-"
JPEG_SUFFIXES = {".jpg", ".jpeg"}



def canon(value: str | None) -> str:
    """Каноническая форма кода: регистр, пунктуация, латиница/кириллица."""
    text = (value or "").strip().upper().replace("Ё", "Е")
    text = re.sub(r"[^0-9A-ZА-Я]", "", text)
    text = text.translate(HOMO)
    if text.isdigit():
        text = str(int(text))
    return text


def fmt_num(value: float | None) -> str:
    """Число для вывода человеку: ``2700``, а не ``2700.0``; ``None`` — «—»."""
    if value is None:
        return "—"
    return str(int(value)) if float(value).is_integer() else str(value)


def photo_key(profile_name: str, field: str) -> str:
    """Ключ манифеста: имя профиля в ЭК + поле фото."""
    return f"{profile_name}|{field}"


def normalize_photo_rel(value: str) -> str:
    """Путь профиля → путь относительно ``static`` (``images/x.jpg``)."""
    text = value.strip().replace("\\", "/").lstrip("/")
    text = text.removeprefix("static/")
    if text and "/" not in text:
        text = f"images/{text}"
    return text


def manifest_path(db_path: Path) -> Path:
    return db_path.parent / PHOTO_MANIFEST_NAME


def load_photo_manifest(db_path: Path) -> dict[str, dict]:
    path = manifest_path(db_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_photo_manifest(db_path: Path, data: dict[str, dict]) -> None:
    path = manifest_path(db_path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def photo_source_version(source: Path) -> dict:
    """Версия исходника KTM: хэш содержимого и размер."""
    return {"sha256": sha256_file(source), "size": source.stat().st_size}


def write_photo(source: Path, target: Path) -> None:
    """Положить фото KTM в файл ЭК, сохранив JPEG-контракт ``*.jpg``.

    JPEG копируется байт-в-байт; PNG/WebP перекодируются в JPEG (качество 85,
    длинная сторона ≤ 1600) — у ЭК все имена оканчиваются на ``.jpg``, менять
    расширения в БД нельзя, это ломает переименование профиля в приложении.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in JPEG_SUFFIXES:
        shutil.copy2(source, target)
        return
    if Image is None:
        raise RuntimeError(
            "для PNG/WebP нужен Pillow: python -m pip install -r backend/requirements-dev.txt"
        )
    with Image.open(source) as raw:
        image = raw.convert("RGB")
        width, height = image.size
        long_side = max(width, height)
        if long_side > PHOTO_MAX_SIDE:
            scale = PHOTO_MAX_SIDE / long_side
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.Resampling.LANCZOS,
            )
        image.save(target, format="JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)


def backup_images(files: list[Path], db_path: Path, stamp: str) -> Path | None:
    """Скопировать перезаписываемые/удаляемые файлы фото перед изменением."""
    existing = [path for path in files if path.is_file()]
    if not existing:
        return None
    backup_dir = db_path.parent / f"{IMAGE_BACKUP_PREFIX}{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir



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
        if len(fields) < 8:
            continue
        sku, mode, qjson, aliases, lengths, active, photo_thumb, photo_full = fields[:8]
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
            "photo_thumb": photo_thumb,
            "photo_full": photo_full,
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
        "select id, name, quantity_per_hanger, length, photo_thumb, photo_full "
        "from profiles order by name"
    ).fetchall()
    return conn, [
        {
            "id": row[0],
            "name": row[1],
            "n": row[2],
            "length": row[3],
            "photo_thumb": row[4],
            "photo_full": row[5],
        }
        for row in rows
    ]


def photo_plan(product: dict, name: str, targets: PhotoTargets) -> list[dict]:
    """Фото KTM, которые можно положить в ``images/`` под именем профиля."""
    plan = []
    for field, suffix in PHOTO_FIELDS:
        source = product.get(field) or ""
        if not source:
            continue
        source_path = targets.prod_storage / source
        if not source_path.is_file():
            continue
        plan.append({
            "field": field,
            "path": f"{targets.image_prefix}/{name}{suffix}",
            "source": str(source_path),
            "source_rel": source.replace("\\", "/"),
        })
    return plan


def ensure_image(item: dict, targets: PhotoTargets, *, overwrite: bool) -> bool:
    """Положить фото в ``images/``; True — файл на месте.

    ``overwrite`` — для обновления уже занятого поля: в этом режиме файл
    перезаписывается, иначе существующий не трогается (создание профиля).
    """
    target = targets.images_dir / Path(item["path"]).name
    if target.is_file() and not overwrite:
        return True
    write_photo(Path(item["source"]), target)
    return target.is_file()


def compute_drift(
    products: list[dict],
    profiles: list[dict],
    targets: PhotoTargets,
    manifest: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Расхождения с продом: правки существующих, фото и профили на создание."""
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

        # Фото синкаются независимо от длин: профиль может быть без нормы, но
        # с фото. Заполняем пустые поля и обновляем занятые, если исходник KTM
        # изменился с прошлого синка (манифест).
        for item in photo_plan(product, profile["name"], targets):
            current = profile[item["field"]]
            if current and current.strip().lower().startswith(("http://", "https://")):
                skipped.append({
                    "name": profile["name"], "ktm_sku": product["sku"],
                    "reason": "фото задано внешним URL — не трогаем",
                })
                continue
            source_path = Path(item["source"])
            version = photo_source_version(source_path)
            target = item["path"] if not current else normalize_photo_rel(current)
            entry = (manifest or {}).get(photo_key(profile["name"], item["field"]))
            if not current:
                reason = "фото нет в Экранчике"
            elif entry is None:
                reason = "фото обновлено: нет записи в манифесте"
            elif entry.get("source") != item["source_rel"] or entry.get("sha256") != version["sha256"]:
                reason = "фото KTM изменилось"
            else:
                continue
            drift.append({
                "id": profile["id"], "name": profile["name"], "ktm_sku": product["sku"],
                "field": "photo", "photo_field": item["field"],
                "old": current or None, "new": target, "path": target,
                "target": target, "source": item["source"],
                "source_rel": item["source_rel"],
                "source_sha256": version["sha256"], "source_size": version["size"],
                "reason": reason,
            })

        if not product["lengths"]:
            # Длины в KTM нет — норму привязать не к чему, но это не повод
            # считать профиль ошибкой: фото уже синкаются выше, а пустые
            # length/n остаются как есть и заполняются вручную (#403 follow-up).
            continue

        item, _basis = match_length(product, profile["length"])
        if item is None:
            target = main_length(product)
            reason = (
                "длина не задана в Экранчике"
                if profile["length"] is None
                else "нет такой длины в KTM"
            )
            drift.append({"id": profile["id"], "name": profile["name"], "ktm_sku": product["sku"],
                          "field": "length", "old": profile["length"],
                          "new": target["length"], "reason": reason})
            item = target

        target_n = effective_n(product, item["length"])
        if target_n is not None and int(profile["n"] or -1) != target_n:
            drift.append({"id": profile["id"], "name": profile["name"], "ktm_sku": product["sku"],
                          "field": "quantity_per_hanger", "old": profile["n"],
                          "new": target_n, "reason": f"норма для длины {int(item['length'])}"})
        elif target_n is None and profile["n"] is not None:
            skipped.append({"name": profile["name"], "ktm_sku": product["sku"],
                            "reason": "у артикула KTM нет нормы"})

    # Защита от второго профиля с тем же кодом: имя в Экранчике уникально, а
    # сопоставление идёт по канону (регистр, дефисы, латиница/кириллица).
    taken = {canon(profile["name"]) for profile in profiles}
    creations: list[dict] = []
    for product in products:
        key = canon(product["sku"])
        if key in matched_ids:
            continue
        if key in taken:
            skipped.append({"name": product["sku"], "ktm_sku": product["sku"],
                            "reason": "код уже занят профилем Экранчика"})
            continue
        if not product["is_active"]:
            skipped.append({"name": product["sku"], "ktm_sku": product["sku"],
                            "reason": "артикул неактивен в KTM"})
            continue
        if not product["lengths"]:
            # Создаём профиль и без длины: в Экранчике length/n nullable, а
            # пустая карточка полезнее отсутствующей — оператор заполнит её
            # вручную. Фото, если есть, кладём рядом.
            creations.append({
                "name": product["sku"],
                "length": None,
                "n": None,
                "photos": photo_plan(product, product["sku"], targets),
            })
            continue

        target = main_length(product)
        creations.append({
            "name": product["sku"],
            "length": target["length"],
            "n": effective_n(product, target["length"]),
            "photos": photo_plan(product, product["sku"], targets),
        })
    creations.sort(key=lambda item: item["name"])
    return drift, skipped, creations


def seed_manifest(
    db_path: Path,
    products: list[dict],
    profiles: list[dict],
    targets: PhotoTargets,
) -> int:
    """Записать в манифест текущие фото KTM, не перезаписывая картинки.

    Нужен при переходе на манифест: в ЭК уже лежат актуальные (после ручного
    обновления) файлы, и полный перезалив всех фото не нужен. Дальше синк
    обновляет только те фото, чей исходник в KTM изменился.
    """
    by_sku, by_alias = build_index(products)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    manifest: dict[str, dict] = {}
    for profile in profiles:
        product = by_sku.get(canon(profile["name"])) or by_alias.get(canon(profile["name"]))
        if product is None:
            continue
        for item in photo_plan(product, profile["name"], targets):
            if not profile[item["field"]]:
                continue
            source = Path(item["source"])
            version = photo_source_version(source)
            manifest[photo_key(profile["name"], item["field"])] = {
                "source": item["source_rel"],
                "sha256": version["sha256"],
                "size": version["size"],
                "updated_at": now,
            }
    save_photo_manifest(db_path, manifest)
    return len(manifest)


def apply_drift(
    db_path: Path,
    drift: list[dict],
    creations: list[dict],
    targets: PhotoTargets,
    manifest: dict[str, dict] | None = None,
    prune_orphans: bool = False,
    dry_run: bool = False,
) -> dict | None:
    """Записать расхождения в SQLite Экранчика (с бэкапом) и вернуть счётчики."""
    columns = {"length": "length", "quantity_per_hanger": "quantity_per_hanger"}
    updates = [item for item in drift if item["field"] in columns]
    photos = [item for item in drift if item["field"] == "photo"]
    orphans = [item for item in drift if item["field"] == "product"] if prune_orphans else []
    creation_photos = [photo for item in creations for photo in item["photos"]]
    if dry_run or (not updates and not photos and not creations and not orphans):
        return None

    # Конвертацию проверяем до любых записей: иначе PNG упадёт на середине
    # и часть картинок будет уже перезаписана.
    needs_conversion = [
        Path(photo["source"])
        for photo in photos + creation_photos
        if Path(photo["source"]).suffix.lower() not in JPEG_SUFFIXES
    ]
    if needs_conversion and Image is None:
        raise PhotoSyncError(
            "для PNG/WebP нужен Pillow: python -m pip install -r backend/requirements-dev.txt"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    src = sqlite3.connect(db_path, timeout=15)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    created = 0
    pruned = 0
    applied_photos: list[dict] = []
    images_backup: Path | None = None

    conn = sqlite3.connect(db_path, timeout=15)
    try:
        orphan_rows: dict[int, tuple[str | None, str | None]] = {}
        orphan_files: list[Path] = []
        if prune_orphans:
            for item in orphans:
                row = conn.execute(
                    "select photo_thumb, photo_full from profiles where id = ?",
                    (item["id"],),
                ).fetchone()
                if row is None:
                    continue
                orphan_rows[item["id"]] = (row[0], row[1])
                for rel in row:
                    if rel:
                        orphan_files.append(targets.images_dir / Path(normalize_photo_rel(rel)).name)

        # Фото, которые сейчас перезапишем/создадим, и файлы удаляемых профилей —
        # в резервную копию до записи: откат должен быть без потерь.
        images_backup = backup_images(
            [targets.images_dir / Path(item["target"]).name for item in photos]
            + [targets.images_dir / Path(photo["path"]).name for photo in creation_photos]
            + orphan_files,
            db_path,
            stamp,
        )

        # Файлы кладём до записи в БД: путь в профиле означает «файл на месте».
        applied_photos = [item for item in photos if ensure_image(item, targets, overwrite=True)]

        with conn:
            for item in updates:
                conn.execute(
                    f"update profiles set {columns[item['field']]} = ?, updated_at = ? where id = ?",
                    (item["new"], now, item["id"]),
                )
            for item in applied_photos:
                conn.execute(
                    f"update profiles set {item['photo_field']} = ?, updated_at = ? where id = ?",
                    (item["new"], now, item["id"]),
                )
            for item in creations:
                paths = {
                    photo["field"]: photo["path"]
                    for photo in item["photos"]
                    if ensure_image(photo, targets, overwrite=False)
                }
                conn.execute(
                    "insert into profiles "
                    "(name, quantity_per_hanger, length, photo_thumb, photo_full) "
                    "values (?, ?, ?, ?, ?)",
                    (
                        item["name"],
                        item["n"],
                        item["length"],
                        paths.get("photo_thumb"),
                        paths.get("photo_full"),
                    ),
                )
                created += 1
            if prune_orphans:
                for item in orphans:
                    if item["id"] in orphan_rows:
                        conn.execute("delete from profiles where id = ?", (item["id"],))
                        pruned += 1

        # Файлы удалённых профилей убираем только если на них больше никто
        # не ссылается: путь мог быть общим для двух карточек.
        if prune_orphans:
            for rels in orphan_rows.values():
                for rel in rels:
                    if not rel:
                        continue
                    normalized = normalize_photo_rel(rel)
                    still_used = conn.execute(
                        "select count(*) from profiles where photo_thumb = ? or photo_full = ?",
                        (normalized, normalized),
                    ).fetchone()[0]
                    path = targets.images_dir / Path(normalized).name
                    if still_used == 0 and path.is_file():
                        path.unlink()
    finally:
        conn.close()

    if manifest is not None:
        for item in applied_photos:
            manifest[photo_key(item["name"], item["photo_field"])] = {
                "source": item["source_rel"],
                "sha256": item["source_sha256"],
                "size": item["source_size"],
                "updated_at": now,
            }
        for item in creations:
            for photo in item["photos"]:
                target = targets.images_dir / Path(photo["path"]).name
                if not target.is_file():
                    continue
                source = Path(photo["source"])
                manifest[photo_key(item["name"], photo["field"])] = {
                    "source": photo["source_rel"],
                    "sha256": sha256_file(source),
                    "size": source.stat().st_size,
                    "updated_at": now,
                }
        if prune_orphans:
            for item in orphans:
                prefix = f"{item['name']}|"
                for key in [key for key in manifest if key.startswith(prefix)]:
                    del manifest[key]
        save_photo_manifest(db_path, manifest)

    return {
        "backup": backup,
        "images_backup": images_backup,
        "updated": len(updates),
        "created": created,
        "photos": len(applied_photos),
        "pruned": pruned,
    }


# ─── Dev-стенд: прод — источник правды ────────────────────────────────────────


def read_env_file(path: Path) -> dict[str, str]:
    """Плоский разбор env-файла: ``KEY=VALUE``; ``#`` и пустые строки — мимо."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        values[name.strip()] = value.strip()
    return values


def prod_target() -> PgTarget:
    return PgTarget(
        container=os.environ.get("KTM_PG_CONTAINER", "ktm2000-postgres-prod"),
        user=os.environ.get("KTM_PG_USER", "ktm2000_user"),
        database=os.environ.get("KTM_PG_DB", "ktm2000_prod"),
    )


def prod_storage_root() -> Path:
    return Path(os.environ.get("KTM_PROD_STORAGE", DEFAULT_PROD_STORAGE))


def dev_env_available() -> bool:
    """Есть ли dev-стенд, к которому можно ходить (``.env.dev`` с содержимым)."""
    return bool(read_env_file(DEV_ENV_FILE))


def dev_target() -> DevTarget:
    """Dev-адресат из ``.env.dev``. Запись в него — только вне прода."""
    env = read_env_file(DEV_ENV_FILE)
    if not env:
        raise DevSyncError(f"нет {DEV_ENV_FILE.relative_to(ROOT)} — dev-часть не настроена")
    env_name = (env.get("ENV") or "dev").strip().lower()
    if env_name in PROD_ENVS:
        raise DevSyncError(
            f"{DEV_ENV_FILE.name} объявляет ENV={env_name}: писать в этот стенд нельзя"
        )
    pg = PgTarget(
        container=env.get("POSTGRES_CONTAINER_NAME", "ktm2000-postgres"),
        user=env.get("POSTGRES_USER", "postgres"),
        database=env.get("POSTGRES_DB", "ktm2000_dev"),
    )
    prod = prod_target()
    if pg.container == prod.container:
        raise DevSyncError(
            f"dev-контейнер совпал с прод ({pg.container}) — восстановление отменено"
        )
    # STORAGE_ROOT в .env.dev задан относительно backend/: там живёт его CWD.
    storage_raw = env.get("STORAGE_ROOT") or "../data/storage-dev"
    return DevTarget(pg=pg, storage_root=(BACKEND_DIR / storage_raw).resolve(), env_name=env_name)


def psql_rows(target: PgTarget, sql: str) -> list[list[str]]:
    """Строки ``psql -t -A`` без заголовка; табы — разделители полей."""
    proc = subprocess.run(
        ["docker", "exec", target.container, "psql", "-U", target.user, "-d", target.database,
         "-A", "-F", "\t", "--no-align", "-t", "-c", sql],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise DevSyncError(
            f"psql в {target.container} упал: "
            f"{proc.stderr.decode('utf-8', 'replace').strip() or 'без вывода'}"
        )
    return [
        line.split("\t")
        for line in proc.stdout.decode("utf-8").splitlines()
        if line.strip()
    ]


def catalog_map(target: PgTarget, sql: str) -> dict[str, str]:
    return {row[0]: row[1] for row in psql_rows(target, sql) if len(row) >= 2}


def revision(target: PgTarget) -> str:
    rows = psql_rows(target, REVISION_SQL)
    return rows[0][0] if rows else "—"


def compute_dev_drift(prod: PgTarget, dev: DevTarget) -> dict:
    """Чем dev отличается от прода: каталог, пары, фото, ревизия миграций."""
    prod_products = catalog_map(prod, PRODUCTS_SQL)
    dev_products = catalog_map(dev.pg, PRODUCTS_SQL)
    prod_pairs = catalog_map(prod, PAIRS_SQL)
    dev_pairs = catalog_map(dev.pg, PAIRS_SQL)

    catalog_drift = []
    for sku in sorted(prod_products):
        if sku not in dev_products:
            catalog_drift.append({"sku": sku, "reason": "нет в dev"})
        elif prod_products[sku] != dev_products[sku]:
            catalog_drift.append({"sku": sku, "reason": "отличается"})
    for sku in sorted(set(dev_products) - set(prod_products)):
        catalog_drift.append({"sku": sku, "reason": "нет в проде"})

    pair_drift = []
    for key in sorted(prod_pairs):
        if dev_pairs.get(key) != prod_pairs[key]:
            pair_drift.append({"pair": key, "reason": "нет в dev" if key not in dev_pairs else "отличается"})
    for key in sorted(set(dev_pairs) - set(prod_pairs)):
        pair_drift.append({"pair": key, "reason": "нет в проде"})

    photos = [row[0] for row in psql_rows(prod, PHOTO_PATHS_SQL)]
    storage_missing = [
        path for path in photos if not (dev.storage_root / path).is_file()
    ]

    return {
        "products_checked": len(prod_products),
        "pairs_checked": len(prod_pairs),
        "photos_checked": len(photos),
        "catalog_drift": catalog_drift,
        "pair_drift": pair_drift,
        "storage_missing": storage_missing,
        "revision": {"prod": revision(prod), "dev": revision(dev.pg)},
        "storage_root": str(dev.storage_root),
    }


def snapshot_dev(dev: DevTarget) -> Path:
    """Снапшот dev-БД перед переливкой — тот же артефакт, что у ``db:snapshot``.

    Формат и имя совпадают с ``npm run db:snapshot -- dump``: файл
    ``data/backups/snapshots/pre-sync-<дата>.sql`` возвращается оттуда же через
    ``npm run db:snapshot -- restore pre-sync-<дата>``.
    """
    snapshot_dir = ROOT / "data" / "backups" / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005 — имя читает человек
    name = f"pre-sync-{stamp}"
    target = snapshot_dir / f"{name}.sql"
    result = subprocess.run(
        ["docker", "exec", dev.pg.container, "pg_dump", "-U", dev.pg.user,
         "-d", dev.pg.database, "--clean", "--if-exists", "--no-owner"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise DevSyncError(
            f"снапшот dev не снят: {result.stderr.decode('utf-8', 'replace').strip()}; "
            "восстановление отменено"
        )
    target.write_bytes(result.stdout)
    (snapshot_dir / f"{name}.meta.txt").write_text(
        "\n".join(
            [
                f"name={name}",
                "label=pre-sync",
                f"created_at={datetime.now().isoformat(timespec='seconds')}",  # noqa: DTZ005
                f"database={dev.pg.database}",
                f"container={dev.pg.container}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target


def terminate_dev_connections(dev: DevTarget) -> None:
    """Снять соединения dev-backend'а перед пересозданием схемы.

    Пул приложения создан с ``pool_pre_ping=True``, поэтому порванные
    соединения он заменит сам: после восстановления API поднимается без
    рестарта процесса.
    """
    psql_rows(
        dev.pg,
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname = current_database() and pid <> pg_backend_pid()",
    )


def restore_prod_into_dev(prod: PgTarget, dev: DevTarget) -> None:
    """Перелить прод-БД в dev: ``pg_dump`` прода идёт в ``pg_restore`` dev.

    Поток без промежуточного файла: дамп прода уходит прямо на вход restore
    внутри dev-контейнера. ``--clean --if-exists`` пересоздаёт схему целиком,
    ``--single-transaction`` оставляет dev-базу целой, если восстановление
    сорвалось посередине.
    """
    dumper = subprocess.Popen(
        ["docker", "exec", prod.container, "pg_dump", "-U", prod.user, "-d", prod.database,
         "-Fc", "--no-owner", "--no-privileges"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if dumper.stdout is None:  # pragma: no cover — PIPE гарантирует stdout
        raise DevSyncError("pg_dump не отдал поток")
    restorer = subprocess.Popen(
        ["docker", "exec", "-i", dev.pg.container, "pg_restore", "-U", dev.pg.user,
         "-d", dev.pg.database, "--clean", "--if-exists", "--no-owner",
         "--no-privileges", "--single-transaction"],
        stdin=dumper.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Свой дескриптор закрываем: иначе dump не увидит обрыв restore через пайп.
    # Читаем через communicate только у restore: у dump stdout уже закрыт, и
    # communicate() на нём падает в reader-треде («read of closed file»).
    _, restorer_err = restorer.communicate()
    dumper_err = dumper.stderr.read() if dumper.stderr is not None else b""
    dumper.wait()

    if dumper.returncode != 0:
        raise DevSyncError(
            f"pg_dump из {prod.container} упал (код {dumper.returncode}): "
            f"{dumper_err.decode('utf-8', 'replace').strip() or 'без вывода'}; dev не тронут"
        )
    if restorer.returncode != 0:
        raise DevSyncError(
            f"pg_restore в {dev.pg.container} упал (код {restorer.returncode}): "
            f"{restorer_err.decode('utf-8', 'replace').strip() or 'без вывода'}; "
            "транзакция откатана, dev остался прежним"
        )


def copy_storage(prod_root: Path, dev: DevTarget) -> dict[str, int]:
    """Скопировать ``products`` и ``imports`` прода в storage dev.

    Слияние без удаления: файлы, которых нет в проде, но на которые ссылается
    dev, не пропадают. ``backups`` не переносим — у dev своя ротация.
    """
    copied: dict[str, int] = {}
    for name in STORAGE_SCOPES:
        source = prod_root / name
        if not source.is_dir():
            continue
        target_root = dev.storage_root / name
        target_root.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            target = target_root / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            count += 1
        copied[name] = count
    return copied


def sync_dev(apply: bool) -> dict:
    """Проверить (и при ``apply`` — выровнять) dev-стенд по проду."""
    prod = prod_target()
    dev = dev_target()
    before = compute_dev_drift(prod, dev)
    report = {"before": before, "applied": False, "snapshot": None, "copied": {}, "after": None}
    if not apply:
        return report

    report["snapshot"] = str(snapshot_dev(dev))
    terminate_dev_connections(dev)
    restore_prod_into_dev(prod, dev)
    report["copied"] = copy_storage(prod_storage_root(), dev)
    report["applied"] = True
    report["after"] = compute_dev_drift(prod, dev)
    return report


def dev_drift_total(report: dict | None) -> int:
    if not report:
        return 0
    state = report.get("after") or report["before"]
    return (
        len(state["catalog_drift"])
        + len(state["pair_drift"])
        + len(state["storage_missing"])
    )


def print_dev_report(report: dict) -> None:
    state = report.get("after") or report["before"]
    if report["applied"]:
        print(f"[dev] снапшот: {report['snapshot']}")
        copied = ", ".join(f"{name} {count}" for name, count in report["copied"].items()) or "—"
        print(f"[dev] БД восстановлена из прода, storage скопирован: {copied}")
    problems = (
        len(state["catalog_drift"])
        + len(state["pair_drift"])
        + len(state["storage_missing"])
    )
    if problems == 0:
        print(
            f"[dev] совпадает с продом: {state['products_checked']} артикулов, "
            f"{state['pairs_checked']} пар, {state['photos_checked']} фото"
        )
    else:
        print(
            f"[dev] расхождения с продом: каталог {len(state['catalog_drift'])}, "
            f"пары {len(state['pair_drift'])}, файлы фото {len(state['storage_missing'])}"
        )
        for item in state["catalog_drift"]:
            print(f"  {item['sku']}: {item['reason']}")
        for item in state["pair_drift"]:
            print(f"  пара {item['pair']}: {item['reason']}")
        for path in state["storage_missing"][:20]:
            print(f"  нет файла: {path}")
        if len(state["storage_missing"]) > 20:
            print(f"  … и ещё {len(state['storage_missing']) - 20} файлов")
    if state["revision"]["prod"] != state["revision"]["dev"]:
        print(
            f"[dev] ревизия миграций: прод {state['revision']['prod']}, "
            f"dev {state['revision']['dev']} — dev не на ревизии прода, "
            "--apply её выровняет"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Синк каталога KTM -> Экранчик и dev-стенд")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="только проверка (по умолчанию)")
    mode.add_argument("--apply", action="store_true", help="обновить Экранчик и dev-стенд")
    parser.add_argument("--scope", choices=("all", "ekranchik", "dev"), default="all",
                        help="кого синхронизировать: all (по умолчанию), ekranchik или dev")
    parser.add_argument("--db", type=Path, default=None, help="путь к ekranchik.db")
    parser.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    parser.add_argument("--if-enabled", action="store_true",
                        help="работать только при KTM_EKRANCHIK_SYNCGATE=1|true|yes|on")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="удалять профили, которых нет в KTM (только с --apply)")
    parser.add_argument("--seed-manifest", action="store_true",
                        help="записать текущие фото KTM в манифест, не перезаписывая картинки")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.if_enabled:
        value = os.environ.get("KTM_EKRANCHIK_SYNCGATE")
        if value is None:
            print("Синк каталога отключён (KTM_EKRANCHIK_SYNCGATE не установлен).")
            return 0
        if value.strip().lower() not in {"1", "true", "yes", "on"}:
            print(f"Недопустимое значение KTM_EKRANCHIK_SYNCGATE={value!r}.", file=sys.stderr)
            return 2

    want_ekr = args.scope in ("all", "ekranchik")
    want_dev = args.scope in ("all", "dev")

    if args.seed_manifest and not args.apply:
        print("--seed-manifest пишет файл: добавьте --apply", file=sys.stderr)
        return 2
    if args.seed_manifest and not want_ekr:
        print("--seed-manifest работает только для Экранчика (--scope all|ekranchik)",
              file=sys.stderr)
        return 2

    products: list[dict] = []
    profiles: list[dict] = []
    drift: list[dict] = []
    skipped: list[dict] = []
    creations: list[dict] = []
    apply_result: dict | None = None

    if want_ekr:
        db_path = args.db or Path(os.environ.get("EKRANCHIK_DB", DEFAULT_EKR_DB))
        if not db_path.exists():
            print(f"БД Экранчика не найдена: {db_path}", file=sys.stderr)
            return 2
        targets = PhotoTargets.for_db(db_path, prod_storage_root())

        try:
            products = read_ktm_catalog()
        except (RuntimeError, FileNotFoundError) as error:
            print(f"Не удалось прочитать каталог KTM: {error}", file=sys.stderr)
            return 2

        conn, profiles = read_ekr(db_path)
        manifest = load_photo_manifest(db_path)
        if args.seed_manifest:
            seeded = seed_manifest(db_path, products, profiles, targets)
            manifest = load_photo_manifest(db_path)
            print(f"Манифест фото: {seeded} записей ({manifest_path(db_path)})")
        try:
            drift, skipped, creations = compute_drift(products, profiles, targets, manifest)
        finally:
            conn.close()

        if args.apply:
            try:
                apply_result = apply_drift(
                    db_path, drift, creations, targets,
                    manifest=manifest,
                    prune_orphans=args.prune_orphans,
                )
            except PhotoSyncError as error:
                print(f"[Экранчик] {error}", file=sys.stderr)
                return 2
            manifest = load_photo_manifest(db_path)
            conn, profiles = read_ekr(db_path)
            try:
                drift, skipped, creations = compute_drift(products, profiles, targets, manifest)
            finally:
                conn.close()

    dev_report: dict | None = None
    if want_dev:
        if not dev_env_available():
            # Свежий клон без dev-стенда: синк «Экранчика» не должен из-за
            # этого падать, но и молчать о пропуске нельзя.
            print("[dev] пропущено: нет .env.dev — dev-стенд не настроен")
        else:
            try:
                dev_report = sync_dev(apply=args.apply)
            except DevSyncError as error:
                print(f"[dev] {error}", file=sys.stderr)
                return 2

    if args.json:
        print(json.dumps({
            "ok": not drift and not creations and dev_drift_total(dev_report) == 0,
            "scope": args.scope,
            "checked": len(profiles),
            "drift": drift,
            "creations": creations,
            "applied": None if apply_result is None else {
                "updated": apply_result["updated"],
                "created": apply_result["created"],
                "photos": apply_result["photos"],
                "pruned": apply_result["pruned"],
                "backup": str(apply_result["backup"]),
                "images_backup": None if apply_result["images_backup"] is None
                else str(apply_result["images_backup"]),
            },
            "skipped": skipped,
            "dev": dev_report,
        }, ensure_ascii=False, indent=1))
    else:
        if want_ekr:
            if apply_result:
                images_backup = apply_result["images_backup"]
                print(
                    f"Обновлено полей: {apply_result['updated']}, "
                    f"создано профилей: {apply_result['created']}, "
                    f"фото: {apply_result['photos']}, "
                    f"удалено профилей: {apply_result['pruned']}. "
                    f"Бэкап БД: {apply_result['backup']}"
                    + (f"; бэкап фото: {images_backup}" if images_backup else "")
                )
            if drift:
                print(f"Расхождения: {len(drift)} (проверено {len(profiles)} профилей)")
                for item in drift:
                    if item["field"] == "product":
                        print(f"  {item['name']}: {item['reason']}")
                    elif item["field"] == "photo":
                        print(f"  {item['name']}: {item['reason']} ({item['new']})")
                    else:
                        print(f"  {item['name']}: {item['field']} {item['old']} -> {item['new']} ({item['reason']})")
                if not args.prune_orphans and any(item["field"] == "product" for item in drift):
                    print("Профили, которых нет в KTM, не удалены: добавьте --prune-orphans.")
            else:
                print(f"Синк-гейт пройден: {len(profiles)} профилей совпадают с KTM.")
            if creations:
                print(f"Будет создано профилей: {len(creations)}")
                for item in creations:
                    print(f"  {item['name']}: длина {fmt_num(item['length'])}, норма {fmt_num(item['n'])}")
            if skipped:
                print(f"Пропущено (нет данных в KTM): {len(skipped)}")
                for item in skipped:
                    print(f"  {item['name']} ({item['ktm_sku']}): {item['reason']}")
        if dev_report is not None:
            print_dev_report(dev_report)

    has_drift = bool(drift) or bool(creations) or dev_drift_total(dev_report) > 0
    return 0 if not has_drift else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
