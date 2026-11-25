"""Решения заказчика по обзору изображений: снятые расхождения и общие файлы.

Файл — вход, который правится руками (как `visual-truth.csv`), страница выводит
его как есть. Формат: `kind;key;decision;note;checked_by;checked_at`.

* `dimension` — расхождение размеров, `key = <sku>|<источник>` где источник
  `чертёж` или `плакат`; `decision = dismissed` снимает строку из списка.
* `shared` — группа одинаковых файлов, `key` — артикулы через запятую по
  алфавиту; `decision = ok` означает «общий каталожный снимок, проверено».
* `article` — решение по одному артикулу, `decision = foreign` значит «файл не
  про этот артикул».

Зачем отдельный файл: одинаковый файл у нескольких артикулов — не дефект, а
повод посмотреть. Вердикт «посмотрел, всё ок» должен переживать пересборку
страницы, иначе один и тот же список разбирается каждый раз заново.
"""

from __future__ import annotations

from . import common

DECISIONS_PATH = common.ROOT / "docs" / "catalog" / "visual-review-decisions.csv"

HEADER = ("kind", "key", "decision", "note", "checked_by", "checked_at")


def load() -> dict[tuple[str, str], dict]:
    if not DECISIONS_PATH.is_file():
        return {}
    return {
        (row.get("kind", ""), row.get("key", "")): row
        for row in common.read_csv(DECISIONS_PATH)
        if row.get("kind") and row.get("key")
    }


def decision(decisions: dict, kind: str, key: str) -> dict | None:
    return decisions.get((kind, key))


def dismissed(decisions: dict, kind: str, key: str) -> bool:
    row = decision(decisions, kind, key)
    return bool(row) and row.get("decision") == "dismissed"


def foreign_articles(decisions: dict) -> set[str]:
    return {key for (kind, key), row in decisions.items() if kind == "article" and row.get("decision") == "foreign"}
