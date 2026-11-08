"""Версия файла фото для `?v=` (#404): пути, отсутствие файла, batch."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from app.core.config import settings
from app.services.product_photo_version import (
    PhotoVersions,
    photo_file_version,
    photo_file_versions,
    photo_versions_for,
)

MTIME_NS = 1_700_000_000_123_456_789


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(tmp_path))
    photo = tmp_path / "products" / "033_full.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"photo-bytes")
    os.utime(photo, ns=(MTIME_NS, MTIME_NS))
    return tmp_path


def test_relative_storage_path_gets_version(storage: Path) -> None:
    photo = storage / "products" / "033_full.jpg"
    stat = photo.stat()

    assert photo_file_version("products/033_full.jpg") == f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def test_windows_separators_resolve_same_file(storage: Path) -> None:
    expected = photo_file_version("products/033_full.jpg")

    assert photo_file_version("products\\033_full.jpg") == expected


def test_static_url_prefix_is_not_accepted(
    storage: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR-0026: путь только root-relative, `/static/...` — абсолютный."""
    with caplog.at_level(logging.WARNING, logger="app.services.product_photo_version"):
        assert photo_file_version("/static/products/033_full.jpg") is None

    assert "absolute" in caplog.text
    assert photo_file_version("static/products/033_full.jpg") is None


@pytest.mark.parametrize(
    "absolute_path",
    [
        "/app/storage/products/033_full.jpg",
        "C:\\app\\storage\\products\\033_full.jpg",
        "C:/app/storage/products/033_full.jpg",
    ],
)
def test_absolute_paths_are_not_stat_ed(
    storage: Path, absolute_path: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.product_photo_version"):
        assert photo_file_version(absolute_path) is None

    assert "absolute" in caplog.text


def test_path_escaping_storage_root_is_rejected(
    storage: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.services.product_photo_version"):
        assert photo_file_version("products/../../etc/passwd") is None

    assert "escapes" in caplog.text


def test_missing_file_returns_none_and_logs_debug(
    storage: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.services.product_photo_version"):
        assert photo_file_version("products/missing.jpg") is None

    assert "unavailable" in caplog.text
    assert all(record.levelno < logging.WARNING for record in caplog.records)


def test_external_url_has_no_local_version(storage: Path) -> None:
    assert photo_file_version("https://cdn.example.com/033_full.jpg") is None


def test_empty_path_has_no_version() -> None:
    assert photo_file_version(None) is None
    assert photo_file_version("") is None


def test_single_pair_helper_returns_named_versions(storage: Path) -> None:
    thumb = storage / "products" / "033_thumb.jpg"
    thumb.write_bytes(b"thumb")
    os.utime(thumb, ns=(MTIME_NS + 1, MTIME_NS + 1))

    versions = photo_versions_for("products/033_thumb.jpg", "products/033_full.jpg")

    assert isinstance(versions, PhotoVersions)
    assert versions.thumb is not None
    assert versions.full is not None
    assert versions == photo_file_versions(
        [("products/033_thumb.jpg", "products/033_full.jpg")]
    )[0]


def test_batch_versions_align_with_pairs(storage: Path) -> None:
    thumb = storage / "products" / "033_thumb.jpg"
    thumb.write_bytes(b"thumb")
    os.utime(thumb, ns=(MTIME_NS + 1, MTIME_NS + 1))

    versions = photo_file_versions(
        [
            ("products/033_thumb.jpg", "products/033_full.jpg"),
            (None, "products/missing.jpg"),
        ]
    )

    assert versions[0].thumb is not None
    assert versions[0].full is not None
    assert versions[1] == PhotoVersions(None, None)
