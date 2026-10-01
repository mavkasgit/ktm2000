"""Tests for GET /api/backups pagination (limit, offset, total, sort, filters)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from app.api import backups as backups_api


def _write_backup(path: Path, *, mtime: datetime, backup_type: str = "manual", comment: str = "") -> None:
    path.write_bytes(b"backup-data")
    timestamp = mtime.timestamp()
    path.touch()
    import os

    os.utime(path, (timestamp, timestamp))
    meta = {
        "source_db": "ktm2000_test",
        "backup_type": backup_type,
        "comment": comment,
        "format": "archive-v2",
    }
    meta_path = path.with_suffix(path.suffix + ".json")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture
def backups_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(backups_api, "BACKUPS_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_backups_offset_limit_pagination(client, backups_dir: Path) -> None:
    now = datetime.now()
    for index in range(6):
        filename = f"backup_ktm2000_test_{(now - timedelta(days=index)).strftime('%Y-%m-%d_%H-%M-%S')}.zip"
        _write_backup(
            backups_dir / filename,
            mtime=now - timedelta(hours=index),
            backup_type="manual" if index % 2 == 0 else "daily",
            comment=f"comment-{index}",
        )

    first_page = await client.get("/api/backups?limit=2&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["total"] == 6
    assert first_body["limit"] == 2
    assert first_body["offset"] == 0

    second_page = await client.get("/api/backups?limit=2&offset=2")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 2
    assert second_body["total"] == 6

    first_names = {item["filename"] for item in first_body["items"]}
    second_names = {item["filename"] for item in second_body["items"]}
    assert first_names.isdisjoint(second_names)


@pytest.mark.asyncio
async def test_backups_backup_type_filter(client, backups_dir: Path) -> None:
    now = datetime.now()
    _write_backup(
        backups_dir / "backup_ktm2000_test_2026-01-01_10-00-00.zip",
        mtime=now,
        backup_type="daily",
    )
    _write_backup(
        backups_dir / "backup_ktm2000_test_2026-01-02_10-00-00.zip",
        mtime=now - timedelta(hours=1),
        backup_type="manual",
    )

    response = await client.get("/api/backups?backup_type=daily&limit=50&offset=0")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["backup_type"] == "daily"


@pytest.mark.asyncio
async def test_backups_sort_by_size(client, backups_dir: Path) -> None:
    now = datetime.now()
    small = backups_dir / "backup_ktm2000_test_2026-01-01_10-00-00.zip"
    large = backups_dir / "backup_ktm2000_test_2026-01-02_10-00-00.zip"
    small.write_bytes(b"x")
    large.write_bytes(b"x" * 20)
    for path, mtime in ((small, now), (large, now - timedelta(hours=1))):
        import os

        os.utime(path, (mtime.timestamp(), mtime.timestamp()))

    response = await client.get("/api/backups?sort=size:asc&limit=10&offset=0")
    assert response.status_code == 200
    sizes = [item["size"] for item in response.json()["items"]]
    assert sizes == sorted(sizes)


@pytest.mark.asyncio
async def test_backups_sort_two_priorities(client, backups_dir: Path) -> None:
    """Второй приоритет решает порядок внутри групп с одинаковым первым полем.

    Данные засеяны так, что по ``backup_type`` пары идут одинаковыми группами
    и различается только второй ключ. Сортировка одной колонкой (равные внутри
    групп) такой порядок не даёт.
    """
    now = datetime.now()
    # Одинаковый размер и разный mtime: tiebreaker обязан разложить группы
    # по имени файла, а не оставить их в порядке обхода каталога.
    for index, (day, backup_type) in enumerate(
        [
            ("2026-01-01", "daily"),
            ("2026-01-02", "daily"),
            ("2026-01-03", "manual"),
            ("2026-01-04", "manual"),
        ]
    ):
        _write_backup(
            backups_dir / f"backup_ktm2000_test_{day}_10-00-00.zip",
            mtime=now - timedelta(hours=index),
            backup_type=backup_type,
        )

    response = await client.get("/api/backups?sort=backup_type:asc,filename:desc&limit=50")
    assert response.status_code == 200, response.text
    filenames = [item["filename"] for item in response.json()["items"]]
    assert filenames == [
        "backup_ktm2000_test_2026-01-02_10-00-00.zip",
        "backup_ktm2000_test_2026-01-01_10-00-00.zip",
        "backup_ktm2000_test_2026-01-04_10-00-00.zip",
        "backup_ktm2000_test_2026-01-03_10-00-00.zip",
    ]


@pytest.mark.asyncio
async def test_backups_sort_tiebreaker_keeps_pages_stable(client, backups_dir: Path) -> None:
    """Порядок строк детерминирован и одинаков при постраничном обходе.

    Список бэкапов — это файлы на диске, физический порядок обхода каталога
    не гарантирован. У всех файлов одинаковый размер (сортировка по нему всех
    уравнивает), поэтому порядок целиком определяет tiebreaker по имени файла —
    и он должен совпадать на первой и на второй странице.
    """
    now = datetime.now()
    for index in range(6):
        _write_backup(
            backups_dir / f"backup_ktm2000_test_2026-02-{index + 1:02d}_10-00-00.zip",
            mtime=now - timedelta(hours=index),
        )

    full = await client.get("/api/backups?sort=size:asc&limit=50")
    assert full.status_code == 200, full.text
    filenames = [item["filename"] for item in full.json()["items"]]
    assert len(filenames) == 6
    assert len(set(filenames)) == 6

    page2 = await client.get("/api/backups?sort=size:asc&limit=2&offset=2")
    assert page2.status_code == 200, page2.text
    assert [item["filename"] for item in page2.json()["items"]] == filenames[2:4]


@pytest.mark.asyncio
async def test_backups_sort_invalid_field_and_order_400(client, backups_dir: Path) -> None:
    """Молчаливый фолбэк запрещён: поле вне таблицы — 400, не sort по created_at."""
    now = datetime.now()
    _write_backup(backups_dir / "backup_ktm2000_test_2026-01-01_10-00-00.zip", mtime=now)

    unknown_field = await client.get("/api/backups?sort=format:asc")
    assert unknown_field.status_code == 400

    unknown_order = await client.get("/api/backups?sort=size:sideways")
    assert unknown_order.status_code == 400


@pytest.mark.asyncio
async def test_backups_legacy_sort_params_ignored(client, backups_dir: Path) -> None:
    """Сепаратные sort_by/sort_order больше не влияют на порядок.

    FastAPI игнорирует неизвестные query-параметры, поэтому без этой проверки
    фронт, шлёт старую форму, получил бы 200 и тихую сортировку по умолчанию —
    ровно тот молчаливый фолбэк, который запрещён.
    """
    now = datetime.now()
    for index in range(3):
        path = backups_dir / f"backup_ktm2000_test_2026-03-{index + 1:02d}_10-00-00.zip"
        path.write_bytes(b"x" * (10 - index))
        import os

        os.utime(path, ((now - timedelta(hours=index)).timestamp(),) * 2)

    default = await client.get("/api/backups?limit=50")
    legacy = await client.get("/api/backups?sort_by=size&sort_order=asc&limit=50")
    assert default.status_code == 200, default.text
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["items"] == default.json()["items"]


def test_backups_sort_table_keys_match_valid_fields() -> None:
    """Таблица ключей и набор допустимых полей не разъезжаются.

    Ловит дрейф: поле, добавленное в одну сторону и забытое в другой, дало бы
    либо 400 на существующем поле, либо поле в контракте без ключа.
    """
    assert set(backups_api._SORT_KEYS) == backups_api.VALID_SORT_FIELDS
    assert {
        "filename", "db_name", "backup_type", "size", "created_at", "comment",
    } == backups_api.VALID_SORT_FIELDS
    assert set(backups_api._SORT_NULLS_LAST_FIELDS) <= backups_api.VALID_SORT_FIELDS
    assert backups_api._SORT_DEFAULT.field in backups_api.VALID_SORT_FIELDS