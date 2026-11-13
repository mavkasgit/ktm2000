"""Тесты синка фото KTM → «Экранчик» (`scripts/sync-ekranchik.py`).

Проверяют логику манифеста и обновления занятых фото без Docker и прод-БД:
временный SQLite, временный storage, настоящие файлы изображений.
"""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
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


def make_db(path: Path, *, with_description: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    description = "description varchar(500)," if with_description else ""
    conn.executescript(
        f"""
        create table profiles (
            id integer primary key,
            name varchar(255) unique not null,
            quantity_per_hanger integer,
            length float,
            notes text,
            {description}
            photo_thumb varchar(500),
            photo_full varchar(500),
            usage_count integer default 0 not null,
            created_at datetime default current_timestamp not null,
            updated_at datetime default current_timestamp not null
        );
        """
    )
    return conn


def product(
    photo_thumb: str = "",
    photo_full: str = "",
    name: str = "Шланг X",
    is_active: bool = True,
) -> dict:
    return {
        "sku": "X",
        "name": name,
        "mode": "auto",
        "qph": {"2000": {"auto": 10}},
        "aliases": [],
        "lengths": [{"length": 2000.0, "primary": True, "raw": None, "eff_raw": 2000.0}],
        "is_active": is_active,
        "photo_thumb": photo_thumb,
        "photo_full": photo_full,
    }


def profile(
    photo_thumb: str | None = None,
    photo_full: str | None = None,
    description: str | None = None,
) -> dict:
    return {
        "id": 1,
        "name": "X",
        "n": 10,
        "length": 2000.0,
        "description": description,
        "photo_thumb": photo_thumb,
        "photo_full": photo_full,
    }


def test_normalize_photo_rel_strips_static_prefix() -> None:
    assert sync.normalize_photo_rel("/static/images/A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("static\\images\\A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("images/A.jpg") == "images/A.jpg"
    assert sync.normalize_photo_rel("A.jpg") == "images/A.jpg"


def test_photo_refresh_compares_local_and_source_sizes(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    source = storage / "products" / "X_1_full.jpg"
    make_image(source, "red", size=(40, 20))
    images = tmp_path / "images"
    target = images / "X.jpg"
    make_image(target, "blue", size=(20, 10))
    targets = sync.PhotoTargets(images_dir=images, prod_storage=storage)

    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.jpg")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )
    photo = [item for item in drift if item["field"] == "photo"]
    assert len(photo) == 1
    assert photo[0]["reason"].startswith("размер файла отличается")
    assert photo[0]["target"] == "images/X.jpg"

    # Размеры совпали — файл считается тем же и не перезаписывается.
    shutil.copy2(source, target)
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.jpg")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )
    assert not [item for item in drift if item["field"] == "photo"]

    # Файла нет на месте — это тоже расхождение, даже если поле заполнено.
    target.unlink()
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.jpg")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )
    photo = [item for item in drift if item["field"] == "photo"]
    assert len(photo) == 1
    assert photo[0]["reason"] == "файла фото нет в Экранчике"


def test_write_photo_converts_png_to_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "target.jpg"
    make_image(source, size=(2400, 100))

    sync.write_photo(source, target)

    assert target.read_bytes().startswith(JPEG_MAGIC)
    with Image.open(target) as image:
        assert image.size == (1600, 67)
    assert sync.photo_file_size(source) == target.stat().st_size


def test_png_source_is_compared_by_rendered_size(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    source = storage / "products" / "X_1_full.png"
    make_image(source, "red", size=(40, 20))
    images = tmp_path / "images"
    target = images / "X.jpg"
    sync.write_photo(source, target)
    targets = sync.PhotoTargets(images_dir=images, prod_storage=storage)

    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.png")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )

    assert not [item for item in drift if item["field"] == "photo"]


def test_apply_refreshes_photo_and_keeps_path(tmp_path: Path) -> None:
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
    source = storage / "products" / "X_1_full.jpg"
    make_image(source, "red", size=(40, 20))
    targets = sync.PhotoTargets(images_dir=images, prod_storage=storage)

    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.jpg")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )

    result = sync.apply_drift(db_path, drift, [], targets)

    assert result is not None
    assert result["photos"] == 1
    assert (images / "X.jpg").read_bytes() == source.read_bytes()
    assert result["images_backup"] is not None
    assert (result["images_backup"] / "X.jpg").is_file()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("select photo_full from profiles where id = 1").fetchone()[0] == "images/X.jpg"
    finally:
        conn.close()

    # После копии размеры совпадают — повторный синк фото не трогает.
    drift, _skipped, _creations = sync.compute_drift(
        [product(photo_full="products/X_1_full.jpg")],
        [profile(photo_full="images/X.jpg")],
        targets,
    )
    assert not [item for item in drift if item["field"] == "photo"]


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

    result = sync.apply_drift(
        db_path,
        [{"id": 2, "name": "ORPHAN", "field": "product", "reason": "нет в каталоге KTM"}],
        [],
        targets,
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


def drift_fields(drift: list[dict]) -> list[str]:
    return [item["field"] for item in drift]


def test_plan_reports_description_drift_for_empty_and_changed(tmp_path: Path) -> None:
    targets = sync.PhotoTargets(images_dir=tmp_path / "images", prod_storage=tmp_path / "storage")
    products = [product(name="Шланг 2,7 м")]

    empty, _skipped, creations = sync.compute_drift(products, [profile()], targets)
    assert not creations
    description = [item for item in empty if item["field"] == "description"]
    assert len(description) == 1
    assert description[0]["old"] is None
    assert description[0]["new"] == "Шланг 2,7 м"
    assert description[0]["reason"] == "наименование KTM изменилось"

    changed, _skipped, _creations = sync.compute_drift(
        products, [profile(description="Старое имя")], targets
    )
    description = [item for item in changed if item["field"] == "description"]
    assert len(description) == 1
    assert description[0]["old"] == "Старое имя"
    assert description[0]["new"] == "Шланг 2,7 м"

    same, _skipped, _creations = sync.compute_drift(
        products, [profile(description="Шланг 2,7 м")], targets
    )
    assert "description" not in drift_fields(same)


def test_apply_writes_description_and_keeps_notes_and_name(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        conn.execute(
            "insert into profiles (id, name, quantity_per_hanger, length, notes, description) "
            "values (1, 'X', 10, 2000, 'Аналог-X', null)"
        )
    conn.close()
    targets = sync.PhotoTargets(images_dir=tmp_path / "images", prod_storage=tmp_path / "storage")

    drift, _skipped, _creations = sync.compute_drift([product(name="Шланг 2,7 м")], [profile()], targets)
    result = sync.apply_drift(db_path, drift, [], targets)

    assert result is not None
    assert result["updated"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select description, notes, name from profiles where id = 1").fetchone()
    finally:
        conn.close()
    assert row == ("Шланг 2,7 м", "Аналог-X", "X")


def test_inactive_product_is_created_with_description(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path).close()
    targets = sync.PhotoTargets(images_dir=tmp_path / "images", prod_storage=tmp_path / "storage")

    drift, skipped, creations = sync.compute_drift(
        [product(name="Шланг 2,7 м", is_active=False)], [], targets
    )

    assert not drift
    assert [item["name"] for item in skipped] == []
    assert len(creations) == 1
    assert creations[0]["description"] == "Шланг 2,7 м"

    result = sync.apply_drift(db_path, drift, creations, targets)

    assert result is not None
    assert result["created"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select name, description from profiles").fetchone()
    finally:
        conn.close()
    assert row == ("X", "Шланг 2,7 м")


def test_missing_description_column_is_a_clear_error(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path, with_description=False).close()

    with pytest.raises(RuntimeError, match="description"):
        sync.read_ekr(db_path)

    targets = sync.PhotoTargets(images_dir=tmp_path / "images", prod_storage=tmp_path / "storage")
    with pytest.raises(RuntimeError, match="description"):
        sync.apply_drift(db_path, [], [], targets)

