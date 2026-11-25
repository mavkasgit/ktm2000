"""Общие источники для HTML-обзоров каталога.

Один доступ к данным, один способ читать разметку — разные страницы. Логика
каждой страницы лежит в своём модуле (`visual`, `skipped`), здесь только то,
что они делят: прод-БД через контейнер, CSV-источники, storage, превью.
"""

from __future__ import annotations

import base64
import csv
import importlib.util
import io
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "catalog"
TRUTH_PATH = DOCS / "visual-truth.csv"
REGISTER_PATH = DOCS / "ktm-profile-register.csv"
SKIPPED_SEED_PATH = ROOT / "backend" / "app" / "seeds" / "product_1c_skipped.py"

STORAGE_ROOT = Path(os.environ.get("KTM_STORAGE_ROOT", ROOT / "data" / "storage-prod"))
OUT_DIR = Path(os.environ.get("KTM_REVIEWS_DIR", ROOT / "data" / "reviews"))

CONTAINER = os.environ.get("KTM_PROD_CONTAINER", "ktm2000-postgres-prod")
DB_USER = os.environ.get("KTM_PROD_USER", "ktm2000_user")
DB_NAME = os.environ.get("KTM_PROD_DB", "ktm2000_prod")

GENERATED_BY = "scripts/build-catalog-reviews.py"

KIND_LABELS = {
    "drawing": "чертёж",
    "plakat": "плакат",
    "photo": "фото изделия",
    "none": "нет изображения",
}
KIND_ORDER = ("drawing", "plakat", "photo", "none")

REASON_LABELS = {
    "not_mes": "не MES (химия, плёнки, крепёж, СИЗ, газы)",
    "purchased": "покупное (не сырьё MES)",
    "no_catalog": "нет в каталоге, новые артикулы не заводим",
}
REASON_ORDER = ("not_mes", "purchased", "no_catalog")


class SourceError(SystemExit):
    """Источник недоступен — обзор собрать нельзя, и это должно быть видно."""


# ─── Прод-БД ─────────────────────────────────────────────────────────────────


def _psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-A", "-t", "-c", sql],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise SourceError(
            f"psql ({CONTAINER}) не ответил: {result.stderr.strip() or 'unknown error'}\n"
            "Проверь прод-контейнер или задай KTM_PROD_CONTAINER / KTM_PROD_USER / KTM_PROD_DB."
        )
    return result.stdout.strip()


def psql_json(sql: str):
    text = _psql(sql)
    return json.loads(text) if text else []


def psql_rows(sql: str) -> list[str]:
    """Строки простого запроса (без json_agg) — по одной на строку."""
    return [line for line in _psql(sql).splitlines() if line.strip()]


def table_exists(name: str) -> bool:
    rows = psql_rows(f"select to_regclass('public.{name}') is not null;")
    return bool(rows) and rows[0] == "t"


def load_products() -> list[dict]:
    """Артикулы прода с привязанными файлами — все, включая внекаталожные.

    Внекаталожные позиции (`is_catalog_item = false`) в разметку попадают: у них
    есть изображение, и оно живёт в storage. Их не проверяют на «нет строки в
    visual-truth.csv», но строку разметки на них ошибкой не считают.

    `drawing_full` и `visual_origin` появились в миграции 087 — до её применения
    на проде колонок нет, поэтому набор колонок подмешивается по факту.
    """
    have = set(
        psql_rows("select column_name from information_schema.columns where table_name = 'products';")
    )
    extra = ""
    if "drawing_full" in have:
        extra += "p.drawing_full,"
    if "visual_origin" in have:
        extra += "p.visual_origin,"
    sql = f"""
    select coalesce(json_agg(row_to_json(t) order by t.sku), '[]'::json) from (
      select p.id, p.sku, p.name, p.code, p.is_catalog_item,
             p.photo_full, p.photo_thumb, {extra}
             p.aliases,
             coalesce((
               select json_agg(l.length_mm order by l.length_mm)
               from product_lengths l where l.product_id = p.id
             ), '[]'::json) as lengths
      from products p
    ) t;
    """
    return psql_json(sql)


# ─── Файловые источники ──────────────────────────────────────────────────────


def read_csv(path: Path, delimiter: str = ";") -> list[dict]:
    if not path.is_file():
        raise SourceError(f"нет входного файла: {path.relative_to(ROOT).as_posix()}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [
            {(key or "").strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(fh, delimiter=delimiter)
        ]


def load_truth() -> tuple[dict[str, dict], list[str]]:
    """Разметка изображений по артикулам + повторяющиеся артикулы, если есть."""
    truth: dict[str, dict] = {}
    duplicates: list[str] = []
    for row in read_csv(TRUTH_PATH):
        sku = row.get("sku", "")
        if not sku:
            continue
        if sku in truth:
            duplicates.append(sku)
        truth[sku] = row
    return truth, sorted(set(duplicates))


def load_register() -> dict[str, dict]:
    """Справочные поля реестра профилей: периметр, архивный исходник, класс."""
    if not REGISTER_PATH.is_file():
        return {}
    with REGISTER_PATH.open(encoding="utf-8-sig", newline="") as fh:
        return {row["sku"]: row for row in csv.DictReader(fh) if row.get("sku")}


def load_skipped() -> tuple[list[dict], str]:
    """Реестр исключений: таблица, если миграция применена, иначе сид.

    Сид — тот же источник, из которого таблица наполняется, поэтому обзор
    работает и до миграции 088 на проде. Как только таблица появилась, читаем
    её: там живые `decided_at` / `decided_by` и ручные правки.
    """
    if table_exists("product_1c_skipped"):
        rows = psql_json(
            """
            select coalesce(json_agg(json_build_object(
              'code', code, 'name_norm', name_norm, 'reason', reason,
              'note', note, 'decided_at', decided_at, 'decided_by', decided_by
            ) order by reason, code), '[]'::json)
            from product_1c_skipped;
            """
        )
        return rows, "таблица product_1c_skipped (прод-БД)"

    spec = importlib.util.spec_from_file_location("_skipped_seed", SKIPPED_SEED_PATH)
    if spec is None or spec.loader is None:
        raise SourceError(f"не читается сид реестра: {SKIPPED_SEED_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {
            "code": code,
            "name_norm": norm_cell(name),
            "reason": reason,
            "note": None,
            "decided_at": None,
            "decided_by": None,
        }
        for code, name, reason in module.PRODUCT_1C_SKIPPED
    ]
    return rows, "сид backend/app/seeds/product_1c_skipped.py (миграция 088 на проде не применена)"


def norm_cell(value: object) -> str:
    """Нормализация ячейки — копия `import_1c_osv._norm_cell`.

    Дублируется один в один намеренно: обзор обязан показывать ровно то, по чему
    матчится импорт, иначе «в реестре нет» будет правдой только на бумаге.
    """
    return " ".join(str(value or "").replace("\xa0", " ").lower().split())


# ─── Storage ─────────────────────────────────────────────────────────────────


def file_of(rel: str | None) -> Path | None:
    if not rel:
        return None
    return STORAGE_ROOT / rel


def file_state(rel: str | None) -> str:
    """`ok` / `missing` / `none` — состояние файла, привязанного к карточке."""
    if not rel:
        return "none"
    path = file_of(rel)
    return "ok" if path is not None and path.is_file() else "missing"


def thumb_data_uri(rel: str | None, cache: dict[str, str | None], max_side: int = 420) -> str | None:
    """base64-превью файла; `None`, если файла нет или не установлен Pillow."""
    if not rel:
        return None
    if rel in cache:
        return cache[rel]
    path = file_of(rel)
    uri: str | None = None
    if path is not None and path.is_file():
        try:
            from PIL import Image

            with Image.open(path) as source:
                if source.mode in ("RGBA", "LA", "P", "PA"):
                    rgba = source.convert("RGBA")
                    canvas = Image.new("RGB", rgba.size, "white")
                    canvas.paste(rgba, mask=rgba.split()[-1])
                    image = canvas
                else:
                    image = source.convert("RGB")
                image.thumbnail((max_side, max_side), Image.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=82, optimize=True)
            uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception as exc:  # noqa: BLE001 — битый файл не должен ронять обзор
            print(f"! превью не собрано: {rel} — {exc}")
            uri = None
    cache[rel] = uri
    return uri


def full_href(rel: str | None) -> str | None:
    path = file_of(rel)
    if path is None or not path.is_file():
        return None
    return path.resolve().as_uri()


# ─── Сводки ──────────────────────────────────────────────────────────────────


def counts_of(values) -> dict[str, int]:
    return dict(Counter(values))
