"""Тесты синка фото KTM → «Экранчик» (`scripts/sync-ekranchik.py`).

Проверяют логику манифеста и обновления занятых фото без Docker и прод-БД:
временный SQLite, временный storage, настоящие файлы изображений.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync-ekranchik.py"
spec = importlib.util.spec_from_file_location("sync_ekranchik", SCRIPT)
sync = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = sync  # dataclass ищет модуль в sys.modules
spec.loader.exec_module(sync)

JPEG_MAGIC = b"\xff\xd8"


def make_image(path: Path, color: str = "red", size: tuple[int, int] = (20, 10)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def make_jpeg(path: Path, color: str = "blue") -> None:
    make_image(path, color)
    with Image.open(path) as image:
        image.convert("RGB").save(path, format="JPEG")


def make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        create table profiles (
            id integer primary key,
            name varchar(255) unique not null,
            quantity_per_hanger integer,
            length float,
            notes text,
            photo_thumb varchar(500),
            photo_full varchar(500),
            usage_count integer default 0 not null,
            created_at datetime default current_timestamp not null,
            updated_at datetime default current_timestamp not null
        );
        """
    )
    return conn


def product(photo_thumb: str = "", photo_full: str = "") -> dict:
    return {
        "sku": "X",
        "mode": "auto",
        "qph": {"2000": {"auto": 10}},
        "aliases": [],
        "lengths": [{"length": 2000.0, "primary": True, "raw": None, "eff_raw": 2000.0}],
        "is_active": True,
        "photo_thumb": photo_thumb,
        "photo_full": photo_full,
    }


def profile(photo_thumb: str | None = None, photo_full: str | None = None) -> dict:
    return {
        "id": 1,
        "name": "X",
        "n": 10,
        "length": 2000.0,
        "photo_thumb": photo_thumb,
        "photo_full": photo_full,
    }


def test_normalize_photo_rel_strips_static_prefix() -> None:
    assert sync.normalize_photo_rel("/static/images/A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("static\\images\\A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("images/A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("A.jpg") == "images/A.jpg"


def test_photo_refresh_detects_source_change(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    source = storage / "products" / "X_1_full.png"
    make_image(source)
    targets = sync.PhotoTargets(images_dir=tmp_path / "images", prod_storage=storage)

    manifest: dict = {}
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
        manifest,
    )
    photo = [item for item in drift if item["field"] == "photo"]
    assert len(photo) == 1
    assert photo[0]["reason"] == "фото обновлено: нет записи в манифесте"
    assert photo[0]["target"] == "images/X.jpg"

    version = sync.photo_source_version(source)
    manifest = {
        "X|photo_full": {
            "source": "products/X_1_full.png",
            "sha256": version["sha256"],
            "size": version["size"],
        }
    }
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
        manifest,
    )
    assert not [item for item in drift if item["field"] == "photo"]

    manifest["X|photo_full"]["sha256"] = "0" * 64
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
        manifest,
    )
    photo = [item for item in drift if item["field"] == "photo"]
    assert len(photo) == 1
    assert photo[0]["reason"] == "фото KTM изменилось"


def test_write_photo_converts_png_to_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "target.jpg"
    make_image(source, size=(2400, 100))

    sync.write_photo(source, target)

    assert target.read_bytes().startswith(JPEG_MAGIC)
    with Image.open(target) as image:
        assert image.size == (1600, 67)


def test_apply_refreshes_only_changed_photo_and_keeps_path(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        conn.execute(
            "insert into profiles (id, name, quantity_per_hanger, length, photo_thumb, photo_full) "
            "values (1, 'X', 10, 2000, null, 'images/X.jpg')"
        )
    conn.close()

    images = tmp_path / "images"
    make_jpeg(images / "X.jpg", "blue")
    storage = tmp_path / "storage"
    source = storage / "products" / "X_1_full.png"
    make_image(source, "red")
    targets = sync.PhotoTargets(images_dir=images, prod_storage=storage)

    manifest = {
        "X|photo_full": {
            "source": "products/X_1_full.png",
            "sha256": "0" * 64,
            "size": 1,
        }
    }
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
        manifest,
    )

    result = sync.apply_drift(db_path, drift, [], targets, manifest=manifest)

    assert result is not None
    assert result["photos"] == 1
    assert (images / "X.jpg").read_bytes().startswith(JPEG_MAGIC)
    assert result["images_backup"] is not None
    assert (result["images_backup"] / "X.jpg").is_file()
    saved = json.loads((tmp_path / sync.PHOTO_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert saved["X|photo_full"]["sha256"] == sync.photo_source_version(source)["sha256"]
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("select photo_full from profiles where id = 1").fetchone()[0] == "images/X.jpg"
    finally:
        conn.close()


def test_prune_orphans_removes_profile_and_images(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        conn.execute(
            "insert into profiles (id, name, quantity_per_hanger, length, photo_thumb, photo_full) "
            "values (1, 'KEEP', 10, 2000, 'images/KEEP-thumb.jpg', 'images/KEEP.jpg')"
        )
        conn.execute(
            "insert into profiles (id, name, quantity_per_hanger, length, photo_thumb, photo_full) "
            "values (2, 'ORPHAN', null, null, 'images/ORPHAN-thumb.jpg', 'images/ORPHAN.jpg')"
        )
    conn.close()

    images = tmp_path / "images"
    make_jpeg(images / "ORPHAN.jpg")
    make_jpeg(images / "ORPHAN-thumb.jpg")
    make_jpeg(images / "KEEP.jpg")
    make_jpeg(images / "KEEP-thumb.jpg")
    targets = sync.PhotoTargets(images_dir=images, prod_storage=tmp_path / "storage")

    manifest = {"ORPHAN|photo_full": {"source": "products/ORPHAN_full.jpg", "sha256": "x", "size": 1}}
    result = sync.apply_drift(
        db_path,
        [{"id": 2, "name": "ORPHAN", "field": "product", "reason": "нет в каталоге KTM"}],
        [],
        targets,
        manifest=manifest,
        prune_orphans=True,
    )

    assert result is not None
    assert result["pruned"] == 1
    assert not (images / "ORPHAN.jpg").exists()
    assert not (images / "ORPHAN-thumb.jpg").exists()
    assert (images / "KEEP.jpg").exists()
    assert result["images_backup"] is not None
    assert (result["images_backup"] / "ORPHAN.jpg").is_file()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("select count(*) from profiles where id = 2").fetchone()[0] == 0
        assert conn.execute("select count(*) from profiles where id = 1").fetchone()[0] == 1
    finally:
        conn.close()
    saved = json.loads((tmp_path / sync.PHOTO_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert "ORPHAN|photo_full" not in saved


def test_seed_manifest_records_existing_photos_without_rewriting(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path).close()
    images = tmp_path / "images"
    target = images / "X.jpg"
    make_jpeg(target, "green")
    before = target.read_bytes()
    storage = tmp_path / "storage"
    source = storage / "products" / "X_1_full.png"
    make_image(source, "red")
    targets = sync.PhotoTargets(images_dir=images, prod_storage=storage)

    count = sync.seed_manifest(
        db_path,
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )

    assert count == 1
    assert target.read_bytes() == before
    saved = json.loads((tmp_path / sync.PHOTO_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert saved["X|photo_full"]["sha256"] == sync.photo_source_version(source)["sha256"]
