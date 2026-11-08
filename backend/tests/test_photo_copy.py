"""Копирование фото при импорте не сбрасывает версию неизменённого файла (#404)."""

from __future__ import annotations

import os
from pathlib import Path

from app.services.photo_copy import copy_photo_if_changed

OLD_MTIME_NS = 1_700_000_000_000_000_000
SOURCE_MTIME_NS = 1_700_000_500_000_000_000


def test_same_bytes_are_not_copied_and_mtime_is_kept(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"same-photo")
    dst.write_bytes(b"same-photo")
    os.utime(src, ns=(SOURCE_MTIME_NS, SOURCE_MTIME_NS))
    os.utime(dst, ns=(OLD_MTIME_NS, OLD_MTIME_NS))

    copied = copy_photo_if_changed(src, dst)

    assert copied is False
    assert dst.stat().st_mtime_ns == OLD_MTIME_NS
    assert dst.read_bytes() == b"same-photo"


def test_changed_bytes_are_copied_with_source_mtime(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"new-photo")
    dst.write_bytes(b"old-photo")
    os.utime(src, ns=(SOURCE_MTIME_NS, SOURCE_MTIME_NS))
    os.utime(dst, ns=(OLD_MTIME_NS, OLD_MTIME_NS))

    copied = copy_photo_if_changed(src, dst)

    assert copied is True
    assert dst.read_bytes() == b"new-photo"
    assert dst.stat().st_mtime_ns == src.stat().st_mtime_ns


def test_missing_destination_is_copied(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"photo")

    assert copy_photo_if_changed(src, dst) is True
    assert dst.read_bytes() == b"photo"
