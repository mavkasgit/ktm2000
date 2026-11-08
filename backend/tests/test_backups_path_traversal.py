"""Имя файла бэкапа из URL не выводит за ``BACKUPS_DIR`` (#безопасность).

Роутер не пропускает ``/`` в path-параметре, но на Windows разделителем
работает и обратный слэш: ``..\\..\\secret`` доезжает до ``Path`` одной
компонентой. Проверяем и хелпер, и сам эндпоинт скачивания.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.api import backups as backups_api
from fastapi import HTTPException


@pytest.fixture
def backups_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "backups"
    directory.mkdir()
    monkeypatch.setattr(backups_api, "BACKUPS_DIR", directory)
    return directory


@pytest.mark.parametrize(
    "name",
    [
        "..",
        ".",
        "",
        "../secret.txt",
        "..\\secret.txt",
        "sub/backup.zip",
        "sub\\backup.zip",
        "backup\x00.zip",
    ],
)
def test_backup_file_path_rejects_escape(name: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        backups_api._backup_file_path(name)
    assert exc_info.value.status_code == 404


def test_backup_file_path_accepts_plain_name(backups_dir: Path) -> None:
    assert backups_api._backup_file_path("backup_ktm2000_test.zip") == (
        backups_dir / "backup_ktm2000_test.zip"
    )


async def test_download_does_not_read_outside_backups_dir(
    client, backups_dir: Path
) -> None:
    secret = backups_dir.parent / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")

    response = await client.get("/api/backups/..%5Csecret.txt/download")

    assert response.status_code == 404
    assert "top-secret" not in response.text
