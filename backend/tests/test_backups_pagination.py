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

    response = await client.get("/api/backups?sort_by=size&sort_order=asc&limit=10&offset=0")
    assert response.status_code == 200
    sizes = [item["size"] for item in response.json()["items"]]
    assert sizes == sorted(sizes)