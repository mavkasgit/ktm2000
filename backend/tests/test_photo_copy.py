"""Копирование фото при импорте не сбрасывает версию неизменённого файла (#404)."""

from __future__ import annotations

import os
from pathlib import Path

from app.services.photo_copy import copy_photo_if_changed

OLD_MTIME_NS = 1_700_000_000_000_000_000
SOURCE_MTIME_NS = 1_700_000_500_000_000_000


def _version(path: Path) -> str:
    """Та же пара, из которой считается `?v=` (mtime_ns + size)."""
    file_stat = path.stat()
    return f"{file_stat.st_mtime_ns:x}-{file_stat.st_size:x}"


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


def test_changed_bytes_are_copied_and_get_fresh_mtime(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"new-photo")
    dst.write_bytes(b"old-photo")
    os.utime(src, ns=(SOURCE_MTIME_NS, SOURCE_MTIME_NS))
    os.utime(dst, ns=(OLD_MTIME_NS, OLD_MTIME_NS))
    before_version = _version(dst)

    copied = copy_photo_if_changed(src, dst)

    assert copied is True
    assert dst.read_bytes() == b"new-photo"
    # mtime не переносится из источника копированием: версия обязана
    # измениться даже при совпадении размера и mtime у старого файла.
    assert dst.stat().st_mtime_ns != SOURCE_MTIME_NS
    assert _version(dst) != before_version


def test_same_size_different_bytes_same_mtime_change_version(tmp_path: Path) -> None:
    """Разные байты одного размера с одинаковым mtime ранее давали ту же версию."""
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"AAAA")
    dst.write_bytes(b"BBBB")
    os.utime(src, ns=(SOURCE_MTIME_NS, SOURCE_MTIME_NS))
    os.utime(dst, ns=(SOURCE_MTIME_NS, SOURCE_MTIME_NS))
    before_version = _version(dst)

    copied = copy_photo_if_changed(src, dst)

    assert copied is True
    assert dst.read_bytes() == b"AAAA"
    assert _version(dst) != before_version


def test_missing_destination_is_copied(tmp_path: Path) -> None:
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"
    src.write_bytes(b"photo")

    assert copy_photo_if_changed(src, dst) is True
    assert dst.read_bytes() == b"photo"
