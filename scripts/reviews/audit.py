"""Проверки подлинности изображений: размеры и общие файлы (#463).

Два вопроса, на которые обзор должен отвечать без ручного поиска:

* **Совпадают ли размеры** на чертеже и на плакате с тем, что записано в БД.
  Источник — аудит `assets/catalog-audit/dimensions/dimensions-reconciled.csv`:
  там уже прочитаны периметры с архивного чертежа (`perimeter_archive`) и с
  каталожного плаката (`perimeter_poster`), рядом — периметр из БД.
* **Не выдан ли чужой файл за свой.** Если один и тот же файл (байт в байт)
  привязан к нескольким артикулам, то либо это честный алиас и он должен быть
  помечен `origin=alias`, либо картинка не про этот артикул.

Ни та, ни другая проверка ничего не правит: расхождение — это вердикт
заказчика, а не повод переписать периметр или проставить алиас молча.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from . import common

DIMENSIONS_PATH = common.ROOT / "assets" / "catalog-audit" / "dimensions" / "dimensions-reconciled.csv"

# Меньше этого плакатное расхождение считаем округлением каталожного листа и в
# список не выносим; у чертежа показываем всё, что не ноль.
POSTER_TOLERANCE = 0.5
EXACT = 0.05


def _num(value) -> float | None:
    try:
        return round(float(str(value).replace(",", ".")), 3)
    except (TypeError, ValueError):
        return None


def load_dimensions() -> dict[str, dict]:
    if not DIMENSIONS_PATH.is_file():
        return {}
    return {
        row["sku"]: row for row in common.read_csv(DIMENSIONS_PATH, delimiter=",") if row.get("sku")
    }


def perimeter_rows(
    dimensions: dict[str, dict], truth: dict[str, dict], decisions: dict | None = None
) -> list[dict]:
    """Периметр с чертежа против БД, по убыванию расхождения.

    Считаем только чертёж: плакат — визуальное подтверждение, а не измерение,
    поэтому его периметр в сверке не участвует вовсе (решение заказчика).
    Снятые решениями строки не выводятся.
    """
    decisions = decisions or {}
    rows: list[dict] = []
    for sku, source in dimensions.items():
        db = _num(source.get("perimeter_db"))
        value = _num(source.get("perimeter_archive"))
        if db is None or value is None:
            continue
        delta = round(abs(db - value), 3)
        if delta <= EXACT:
            continue
        decision = decisions.get(("dimension", f"{sku}|чертёж"))
        if decision and decision.get("decision") in ("dismissed", "fixed"):
            continue
        rows.append(
            {
                "sku": sku,
                "source": "чертёж",
                "db": db,
                "image": value,
                "delta": delta,
                "file": source.get("archive_file") or "",
                "kind": (truth.get(sku) or {}).get("kind", ""),
                "severity": "error" if delta >= 0.5 else "warn",
            }
        )
    rows.sort(key=lambda row: (-row["delta"], row["sku"]))
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duplicate_files(
    products: list[dict],
    truth: dict[str, dict],
    cache: dict[str, str | None] | None = None,
    decisions: dict | None = None,
) -> list[dict]:
    """Группы артикулов, у которых слот фото — один и тот же файл байт в байт.

    Превью (`photo_thumb`) не считаем отдельным слотом: это тот же кадр меньшего
    размера, группы совпадали бы дважды.

    Общий файл — не дефект: семейный каталожный снимок законно один на группу.
    Поэтому рядом лежит решение (`shared/*: ok`) и список артикулов, для которых
    файл признан чужим (`article/*: foreign`).
    """
    decisions = decisions or {}
    cache = {} if cache is None else cache
    groups: dict[str, list[dict]] = defaultdict(list)
    for product in products:
        rel = product.get("photo_full")
        if not rel:
            continue
        if rel not in cache:
            path = common.file_of(rel)
            cache[rel] = _sha256(path) if path is not None and path.is_file() else None
        digest = cache[rel]
        if digest:
            groups[digest].append(product)

    foreign = {
        key
        for (kind, key), row in decisions.items()
        if kind == "article" and row.get("decision") == "foreign"
    }
    result: list[dict] = []
    for digest, members in groups.items():
        if len(members) < 2:
            continue
        skus = sorted(member["sku"] for member in members)
        marked = [member["sku"] for member in members if (truth.get(member["sku"]) or {}).get("origin") == "alias"]
        others = [member["sku"] for member in members if member["sku"] not in marked]
        state = decisions.get(("shared", ",".join(skus)))
        result.append(
            {
                "hash": digest[:8],
                "members": others + marked,
                "skus": skus,
                "marked": marked,
                "unmarked": others,
                "foreign": [sku for sku in skus if sku in foreign],
                "kind": (truth.get(members[0]["sku"]) or {}).get("kind", ""),
                "file": members[0].get("photo_full"),
                "state": (state or {}).get("decision", ""),
                "state_note": (state or {}).get("note", ""),
            }
        )
    result.sort(key=lambda group: (-len(group["members"]), group["members"][0]))
    return result


def summary(rows: list[dict], groups: list[dict]) -> dict:
    return {
        "conflicts": len(rows),
        "big_conflicts": sum(1 for row in rows if row["severity"] == "error"),
        "duplicate_groups": len(groups),
        "duplicate_unmarked": sum(len(group["unmarked"]) for group in groups if not group["marked"]),
        "duplicate_articles": sum(len(group["members"]) for group in groups),
        "duplicate_reviewed": sum(1 for group in groups if group["state"] == "ok"),
    }
