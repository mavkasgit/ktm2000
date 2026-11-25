"""Инвентарь архива чертежей: что лежит в папках и что из этого привязано к артикулам.

Архив `Чертежи` рядом с репозиторием — сырьё (PDF/JPG/сканы), в показ не идёт.
Скрипт отвечает на два вопроса заказчика: какие пути есть (чтобы перевести их
дополнительно) и какие ссылки реестра ведут в пустоту.

  python scripts/archive-inventory.py

Пишет:
  data/backups/catalog/archive-files.csv     — все файлы: путь, папка, тип, размер
  data/backups/catalog/archive-drawings.csv  — только чертежи РП/КТМ (PDF/JPG) с полным путём
и печатает сводку.
"""

from __future__ import annotations

import csv
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path(os.environ.get("KTM_ARCHIVE", ROOT.parent / "Чертежи"))
REGISTER = ROOT / "docs" / "catalog" / "ktm-profile-register.csv"
OUT = ROOT / "data" / "backups" / "catalog" / "archive-files.csv"
DRAWINGS = ROOT / "data" / "backups" / "catalog" / "archive-drawings.csv"

DRAWING_FOLDERS = ("РП", "КТМ")
DRAWING_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PATH_LIKE = re.compile(r"^(?:РП|КТМ|Для Л|static)/.+\.(?:pdf|jpe?g|png)$", re.IGNORECASE)


def main() -> int:
    if not ARCHIVE.is_dir():
        raise SystemExit(f"нет папки архива: {ARCHIVE} (задай KTM_ARCHIVE)")

    files = sorted((path for path in ARCHIVE.rglob("*") if path.is_file()), key=lambda p: p.as_posix().lower())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["path", "folder", "ext", "size", "abs_path"])
        for path in files:
            rel = path.relative_to(ARCHIVE)
            writer.writerow(
                [
                    rel.as_posix(),
                    rel.parts[0] if len(rel.parts) > 1 else "",
                    path.suffix.lower(),
                    path.stat().st_size,
                    str(path),
                ]
            )

    drawings = [
        path
        for path in files
        if path.relative_to(ARCHIVE).parts[0] in DRAWING_FOLDERS and path.suffix.lower() in DRAWING_EXT
    ]
    with DRAWINGS.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["folder", "name", "size", "abs_path"])
        for path in drawings:
            rel = path.relative_to(ARCHIVE)
            writer.writerow([rel.parts[0], path.name, path.stat().st_size, str(path)])

    by_folder = Counter(
        path.relative_to(ARCHIVE).parts[0] if len(path.relative_to(ARCHIVE).parts) > 1 else "—"
        for path in files
    )
    by_ext = Counter(path.suffix.lower() for path in files)
    print(f"архив: {ARCHIVE}")
    print(f"файлов: {len(files)}, объём: {sum(p.stat().st_size for p in files) / (1024 * 1024):.1f} МБ")
    print("по папкам: " + ", ".join(f"{name} — {count}" for name, count in sorted(by_folder.items())))
    print("по типам: " + ", ".join(f"{ext or 'без'} — {count}" for ext, count in by_ext.most_common()))
    print(f"чертежей РП/КТМ (PDF/JPG): {len(drawings)}")
    for folder in DRAWING_FOLDERS:
        count = sum(1 for path in drawings if path.relative_to(ARCHIVE).parts[0] == folder)
        print(f"  {folder}: {count}")
    print(f"все файлы:  {OUT.relative_to(ROOT).as_posix()}")
    print(f"чертежи:    {DRAWINGS.relative_to(ROOT).as_posix()}")

    if not REGISTER.is_file():
        return 0
    with REGISTER.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    referenced = [
        (row["sku"], row["archive_file"].strip())
        for row in rows
        if PATH_LIKE.match(row.get("archive_file", "").strip())
    ]
    missing = []
    for sku, rel in referenced:
        if not (ARCHIVE / rel).is_file():
            matches = [path for path in files if path.name.lower() == Path(rel).name.lower()]
            missing.append((sku, rel, matches[0].relative_to(ARCHIVE).as_posix() if matches else None))
    print(f"ссылок-путей из реестра: {len(referenced)}, не находятся по точному пути: {len(missing)}")
    for sku, rel, found in missing:
        tail = f" (есть как {found})" if found else " (нет вовсе)"
        print(f"  {sku:<14} {rel}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
