"""Имя файла бэкапа из URL не выводит за ``BACKUPS_DIR`` (#безопасность).

Роутер не пропускает ``/`` в path-параметре, но на Windows разделителем
работает и обратный слэш: ``..\\..\\secret`` доезжает до ``Path`` одной
компонентой. Проверяем и хелпер, и сам эндпоинт скачивания.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from app.api import backups as backups_api
from fastapi import HTTPException


def _make_escape_link(link: Path, target: Path) -> None:
    """Создаёт ссылку с ``link`` на каталог ``target`` (вне ``BACKUPS_DIR``).

    На POSIX — обычный symlink. На Windows symlink требует Developer Mode или
    права администратора, поэтому используется junction: он создаётся без
    привилегий и так же разрешается ``Path.resolve()`` — проверяется тот же
    второй рубеж хелпера, без платформенного skip.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as exc:
        if sys.platform != "win32":
            pytest.skip(f"symlink creation is not permitted on this host: {exc}")
        symlink_error = exc

    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(
            "neither symlink nor junction creation is permitted on this host: "
            f"symlink={symlink_error}; junction={completed.stderr or completed.stdout}"
        )


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
        "..\\..\\secret.txt",
        "sub/backup.zip",
        "sub\\backup.zip",
        "backup\x00.zip",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "\\\\server\\share\\secret.txt",
        "%2e%2e/secret.txt",
        "/etc/passwd",
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


def test_backup_file_path_rejects_symlink_escape(
    backups_dir: Path, tmp_path: Path
) -> None:
    """Имя без разделителей, но ссылка внутри каталога ведёт наружу.

    Windows без Developer Mode не даёт создать symlink — там ссылка строится
    junction'ом (``_make_escape_link``), и кейс всё равно выполняется.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top-secret", encoding="utf-8")
    link = backups_dir / "backup_link.zip"
    _make_escape_link(link, outside)

    with pytest.raises(HTTPException) as exc_info:
        backups_api._backup_file_path(link.name)
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/backups/..%5C..%5Csecret.txt/download", None),
        ("GET", "/api/backups/%2e%2e%2fsecret.txt/download", None),
        ("PATCH", "/api/backups/..%5C..%5Csecret.txt/comment", {"comment": "x"}),
        ("DELETE", "/api/backups/..%5C..%5Csecret.txt", None),
        ("POST", "/api/backups/..%5C..%5Csecret.txt/preview", None),
        ("POST", "/api/backups/..%5C..%5Csecret.txt/restore", {"db_name": "x"}),
    ],
)
async def test_every_filename_endpoint_rejects_traversal(
    client, backups_dir: Path, monkeypatch: pytest.MonkeyPatch,
    method: str, path: str, payload: dict | None,
) -> None:
    """Ни одна ручка с ``{filename}`` не строит путь мимо helper'а."""
    monkeypatch.setattr(backups_api, "_get_db_name", lambda: "x")
    response = await client.request(method, path, json=payload)
    assert response.status_code == 404, response.text


async def test_bulk_delete_rejects_traversal(client, backups_dir: Path) -> None:
    response = await client.post(
        "/api/backups/bulk-delete",
        json={"filenames": ["..\\..\\secret.txt"]},
    )
    assert response.status_code == 404, response.text
