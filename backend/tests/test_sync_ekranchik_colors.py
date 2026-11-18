"""Тесты синка цветов и безразмерных артикулов KTM → «Экранчик».

Шов — чистые функции плана (``compute_color_drift``, ``compute_drift``),
``apply_drift`` на временном SQLite и ``main`` на временной копии БД.
Docker и прод-БД не нужны: строки KTM — фикстуры в форме
``read_ktm_colors`` / ``read_ktm_catalog``.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync-ekranchik.py"
spec = importlib.util.spec_from_file_location("sync_ekranchik_colors", SCRIPT)
sync = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = sync  # dataclass ищет модуль в sys.modules
spec.loader.exec_module(sync)

OLD = "2026-01-01 00:00:00"
NEW = "2026-06-01 12:00:00"
EQUAL = "2026-03-01 09:30:00"

COLORS_SCHEMA = """
create table colors (
    id integer primary key autoincrement,
    code varchar(16),
    name varchar(120) not null,
    abbreviation varchar(8) not null,
    hex varchar(7),
    operation_code varchar(64) unique,
    source varchar(8) not null default 'local',
    updated_at datetime default current_timestamp not null,
    created_at datetime default current_timestamp not null
);
"""


def make_db(path: Path, *, with_colors: bool = True) -> sqlite3.Connection:
    """Временная копия Экранчика: ``profiles`` (миграция 002) и ``colors`` (003)."""
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        create table profiles (
            id integer primary key,
            name varchar(255) unique not null,
            quantity_per_hanger integer,
            length float,
            notes text,
            description varchar(500),
            photo_thumb varchar(500),
            photo_full varchar(500),
            usage_count integer default 0 not null,
            created_at datetime default current_timestamp not null,
            updated_at datetime default current_timestamp not null
        );
        {COLORS_SCHEMA if with_colors else ""}
        """
    )
    return conn


def targets(tmp_path: Path) -> object:
    return sync.PhotoTargets(
        images_dir=tmp_path / "images", prod_storage=tmp_path / "storage"
    )


def ktm_color(
    operation_code: str,
    name: str,
    hex: str = "#123456",
    updated_at: str = NEW,
) -> dict:
    return {
        "operation_code": operation_code,
        "name": name,
        "hex": hex,
        "updated_at": updated_at,
    }


def local_color(
    row_id: int,
    name: str,
    *,
    code: str | None = None,
    hex: str | None = None,
    operation_code: str | None = None,
    source: str = "local",
    updated_at: str = OLD,
) -> dict:
    return {
        "id": row_id,
        "code": code,
        "name": name,
        "hex": hex,
        "operation_code": operation_code,
        "source": source,
        "updated_at": updated_at,
    }


def insert_color(conn: sqlite3.Connection, **row: object) -> None:
    row.setdefault(
        "abbreviation", row.get("code") or str(row["name"]).strip()[:3].lower()
    )
    conn.execute(
        "insert into colors "
        "(id, code, name, abbreviation, hex, operation_code, source, updated_at) "
        "values (:id, :code, :name, :abbreviation, :hex, :operation_code, "
        ":source, :updated_at)",
        row,
    )


def color_rows(db_path: Path) -> dict[int, dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {row["id"]: dict(row) for row in conn.execute("select * from colors")}
    finally:
        conn.close()


def color_by_id(drift: list[dict], row_id: int) -> dict:
    matches = [item for item in drift if item["id"] == row_id]
    assert len(matches) == 1, drift
    return matches[0]


def parse_db_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def product(
    *,
    sku: str = "X",
    name: str = "Шланг X",
    mode: str = "auto",
    qph: dict | None = None,
    lengths: list[dict] | None = None,
) -> dict:
    return {
        "sku": sku,
        "name": name,
        "mode": mode,
        "qph": {"2000": {"auto": 10}} if qph is None else qph,
        "aliases": [],
        "lengths": (
            [{"length": 2000.0, "primary": True, "raw": None, "eff_raw": 2000.0}]
            if lengths is None
            else lengths
        ),
        "is_active": True,
        "photo_thumb": "",
        "photo_full": "",
    }


def profile(
    *,
    row_id: int = 1,
    name: str = "X",
    n: int | None = 10,
    length: float | None = 2000.0,
    description: str | None = None,
) -> dict:
    return {
        "id": row_id,
        "name": name,
        "n": n,
        "length": length,
        "description": description,
        "photo_thumb": None,
        "photo_full": None,
    }


# ─── Цвета: план и запись ────────────────────────────────────────────────────


def test_missing_color_is_created_from_ktm(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path).close()

    drift, skipped = sync.compute_color_drift(
        [ktm_color("C54", "Тёмный титан", "#2B2B2B", NEW)], []
    )

    assert skipped == []
    assert len(drift) == 1
    item = drift[0]
    assert item["id"] is None
    assert item["operation_code"] == "C54"
    assert item["new"] == {
        "code": "C54",
        "name": "Тёмный титан",
        "hex": "#2B2B2B",
        "source": "ktm",
    }

    result = sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    assert result is not None
    assert result["colors"] == {"updated": 0, "created": 1}
    rows = color_rows(db_path)
    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert row["code"] == "C54"
    assert row["operation_code"] == "C54"
    assert row["abbreviation"] == "C54"
    assert row["name"] == "Тёмный титан"
    assert row["hex"] == "#2B2B2B"
    assert row["source"] == "ktm"
    assert parse_db_time(row["updated_at"]) == parse_db_time(NEW)


def test_newer_ktm_color_overwrites_local(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn,
            id=1,
            code="C31",
            name="Шампань светлая",
            abbreviation="сш",
            hex="#111111",
            operation_code="C31",
            source="local",
            updated_at=OLD,
        )
    conn.close()

    drift, skipped = sync.compute_color_drift(
        [ktm_color("C31", "Светлая шампань", "#F7E7CE", NEW)],
        [local_color(1, "Шампань светлая", code="C31", hex="#111111",
                     operation_code="C31", updated_at=OLD)],
    )

    assert skipped == []
    assert len(drift) == 1
    assert drift[0]["id"] == 1
    assert drift[0]["old"]["name"] == "Шампань светлая"
    assert drift[0]["new"]["name"] == "Светлая шампань"
    assert drift[0]["new"]["hex"] == "#F7E7CE"

    result = sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    assert result is not None
    assert result["colors"] == {"updated": 1, "created": 0}
    row = color_rows(db_path)[1]
    assert row["name"] == "Светлая шампань"
    assert row["hex"] == "#F7E7CE"
    assert row["abbreviation"] == "сш"  # локальная подпись не перезаписывается
    assert row["source"] == "ktm"
    assert parse_db_time(row["updated_at"]) == parse_db_time(NEW)

    # Повторный план по записанному состоянию чист.
    drift, skipped = sync.compute_color_drift(
        [ktm_color("C31", "Светлая шампань", "#F7E7CE", NEW)],
        [_local_from_row(row)],
    )
    assert drift == []
    assert skipped == []


def _local_from_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "hex": row["hex"],
        "operation_code": row["operation_code"],
        "source": row["source"],
        "updated_at": row["updated_at"],
    }


def test_local_newer_color_survives_apply(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn,
            id=1,
            code="C41",
            name="Медь (правка)",
            hex="#AABBCC",
            operation_code="C41",
            source="local",
            updated_at=NEW,
        )
    conn.close()

    local = local_color(1, "Медь (правка)", code="C41", hex="#AABBCC",
                        operation_code="C41", updated_at=NEW)
    drift, skipped = sync.compute_color_drift(
        [ktm_color("C41", "Медь", "#CD5C5C", OLD)], [local]
    )

    assert drift == []
    assert len(skipped) == 1
    assert skipped[0]["operation_code"] == "C41"
    assert "новее" in skipped[0]["reason"]

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    row = color_rows(db_path)[1]
    assert row["name"] == "Медь (правка)"
    assert row["hex"] == "#AABBCC"
    assert row["source"] == "local"


def test_equal_timestamp_keeps_local_color(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn,
            id=1,
            code="C32",
            name="Тёмная шампань (локально)",
            hex="#123123",
            operation_code="C32",
            source="local",
            updated_at=EQUAL,
        )
    conn.close()

    drift, skipped = sync.compute_color_drift(
        [ktm_color("C32", "Тёмная шампань", "#654321", EQUAL)],
        [local_color(1, "Тёмная шампань (локально)", code="C32", hex="#123123",
                     operation_code="C32", updated_at=EQUAL)],
    )

    assert drift == []
    assert len(skipped) == 1
    assert "совпали" in skipped[0]["reason"]

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    row = color_rows(db_path)[1]
    assert row["name"] == "Тёмная шампань (локально)"
    assert row["hex"] == "#123123"


def test_local_color_without_ktm_pair_survives_apply(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn,
            id=1,
            code="RG",
            name="Rose Gold",
            hex="#B76E79",
            operation_code=None,
            source="local",
            updated_at=OLD,
        )
    conn.close()

    # В KTM есть другой цвет: синк должен записать его и не тронуть RG.
    drift, skipped = sync.compute_color_drift(
        [ktm_color("C0", "Серебро", "#C0C0C0", NEW)],
        [local_color(1, "Rose Gold", code="RG", hex="#B76E79")],
    )
    assert [item["operation_code"] for item in drift] == ["C0"]
    assert skipped == []

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    rows = color_rows(db_path)
    assert len(rows) == 2
    rg = rows[1]
    assert rg["code"] == "RG"
    assert rg["name"] == "Rose Gold"
    assert rg["hex"] == "#B76E79"
    assert rg["operation_code"] is None
    assert rg["source"] == "local"


def test_empty_icon_color_does_not_erase_local_hex(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn,
            id=1,
            code="C33",
            name="Светлая бронза",
            hex="#D9B382",
            operation_code="C33",
            source="local",
            updated_at=OLD,
        )
    conn.close()

    drift, _skipped = sync.compute_color_drift(
        [ktm_color("C33", "Светлая бронза", "", NEW)],
        [local_color(1, "Светлая бронза", code="C33", hex="#D9B382",
                     operation_code="C33")],
    )
    assert all(item["new"]["hex"] == "#D9B382" for item in drift)

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)
    assert color_rows(db_path)[1]["hex"] == "#D9B382"


# ─── Цвета: коллизии старых названий и кодов веера ───────────────────────────


def _seed_colliding_colors(conn: sqlite3.Connection) -> None:
    """Засев 0022 в миниатюре: старые названия без кода и коды веера."""
    rows = [
        (1, None, "серебро", None),
        (2, "C0", "Серебро", "#C0C0C0"),
        (3, None, "черный", None),
        (4, "C35", "Чёрный", "#1C1C1C"),
        (5, None, "золото", None),
        (6, "S120-0", "Золото", "#FFD700"),
        (7, None, "медь", None),
        (8, "C41", "Медь", "#CD5C5C"),
    ]
    for row_id, code, name, hex_value in rows:
        insert_color(
            conn,
            id=row_id,
            code=code,
            name=name,
            hex=hex_value,
            operation_code=None,
            source="local",
            updated_at=OLD,
        )


def test_legacy_operations_keep_named_rows_and_fan_codes_keep_their_own(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        _seed_colliding_colors(conn)
    conn.close()

    ktm = [
        ktm_color("C0", "Серебро", "#C8C8C8", NEW),
        ktm_color("C35", "Чёрный", "#1A1A1A", NEW),
        ktm_color("C41", "Медь", "#C0504D", NEW),
        ktm_color("S120-0", "Золото", "#F5D000", NEW),
        ktm_color("ANOD_01", "Серебро", "#BFBFBF", NEW),
        ktm_color("ANOD_05", "Чёрный", "#191919", NEW),
        ktm_color("ANOD_07", "Медь", "#B85C5C", NEW),
    ]
    local = [
        local_color(1, "серебро"),
        local_color(2, "Серебро", code="C0", hex="#C0C0C0"),
        local_color(3, "черный"),
        local_color(4, "Чёрный", code="C35", hex="#1C1C1C"),
        local_color(5, "золото"),
        local_color(6, "Золото", code="S120-0", hex="#FFD700"),
        local_color(7, "медь"),
        local_color(8, "Медь", code="C41", hex="#CD5C5C"),
    ]

    drift, skipped = sync.compute_color_drift(ktm, local)

    assert skipped == []
    assert {item["id"] for item in drift} == {1, 2, 3, 4, 6, 7, 8}
    assert color_by_id(drift, 1)["operation_code"] == "ANOD_01"
    assert color_by_id(drift, 1)["new"]["code"] is None
    assert color_by_id(drift, 2)["operation_code"] == "C0"
    assert color_by_id(drift, 2)["new"]["code"] == "C0"
    assert color_by_id(drift, 3)["operation_code"] == "ANOD_05"
    assert color_by_id(drift, 3)["new"]["code"] is None
    assert color_by_id(drift, 4)["operation_code"] == "C35"
    assert color_by_id(drift, 4)["new"]["code"] == "C35"
    assert color_by_id(drift, 7)["operation_code"] == "ANOD_07"
    assert color_by_id(drift, 7)["new"]["code"] is None

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    rows = color_rows(db_path)
    assert len(rows) == 8
    assert rows[1]["operation_code"] == "ANOD_01"
    assert rows[1]["code"] is None
    assert rows[1]["name"] == "Серебро"
    assert rows[2]["operation_code"] == "C0"
    assert rows[2]["code"] == "C0"
    assert rows[3]["operation_code"] == "ANOD_05"
    assert rows[3]["code"] is None
    assert rows[4]["operation_code"] == "C35"
    assert rows[4]["code"] == "C35"
    # «золото» без пары в KTM: S120-0 уже носит своё название и код.
    assert rows[5]["operation_code"] is None
    assert rows[5]["source"] == "local"
    assert rows[6]["operation_code"] == "S120-0"


def test_fan_code_matches_by_name_when_seed_row_has_no_code(tmp_path: Path) -> None:
    """Без строки с кодом веера новая операция забирает безымянную по названию."""
    local = [local_color(1, "Тёмная шампань")]
    drift, skipped = sync.compute_color_drift(
        [ktm_color("C32", "Тёмная шампань", "#4A3B2A", NEW)], local
    )

    assert skipped == []
    assert len(drift) == 1
    assert drift[0]["id"] == 1
    assert drift[0]["new"]["code"] == "C32"
    assert drift[0]["operation_code"] == "C32"


def test_legacy_operation_does_not_take_fan_row_by_name(tmp_path: Path) -> None:
    """ANOD_05 «Чёрный» не забирает строку C35: для старой операции нужна пустая."""
    db_path = tmp_path / "ekranchik.db"
    conn = make_db(db_path)
    with conn:
        insert_color(
            conn, id=4, code="C35", name="Чёрный", hex="#1C1C1C",
            operation_code=None, source="local", updated_at=OLD,
        )
    conn.close()

    local = [local_color(4, "Чёрный", code="C35", hex="#1C1C1C")]
    drift, skipped = sync.compute_color_drift(
        [ktm_color("ANOD_05", "Чёрный", "#191919", NEW)], local
    )

    assert skipped == []
    assert len(drift) == 1
    assert drift[0]["id"] is None
    assert drift[0]["operation_code"] == "ANOD_05"
    assert drift[0]["new"]["code"] is None

    sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    rows = color_rows(db_path)
    assert len(rows) == 2
    assert rows[4]["operation_code"] is None  # C35 остался при своём коде
    created = rows[5]
    assert created["operation_code"] == "ANOD_05"
    assert created["code"] is None
    assert created["abbreviation"] == "чёр"


def test_apply_requires_colors_table_only_when_colors_change(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path, with_colors=False).close()

    drift, _skipped = sync.compute_color_drift(
        [ktm_color("C0", "Серебро", "#C0C0C0", NEW)], []
    )

    with pytest.raises(sync.EkranchikSchemaError, match="003"):
        sync.apply_drift(db_path, [], [], targets(tmp_path), color_updates=drift)

    # Без изменений цвета старая схема Экранчика синку продуктов не мешает.
    assert sync.apply_drift(db_path, [], [], targets(tmp_path)) is None


# ─── main: --check / --apply / повторный --check ─────────────────────────────


def test_main_check_apply_check_reports_and_clears_colors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path).close()
    monkeypatch.setattr(sync, "read_ktm_catalog", list)
    monkeypatch.setattr(
        sync,
        "read_ktm_colors",
        lambda: [
            ktm_color("C0", "Серебро", "#C0C0C0", NEW),
            ktm_color("ANOD_01", "Серебро", "#BFBFBF", NEW),
        ],
    )
    args = ["--json", "--db", str(db_path), "--scope", "ekranchik"]

    assert sync.main(["--check", *args]) == 1
    first = json.loads(capsys.readouterr().out)
    assert first["ok"] is False
    assert first["colors"]["checked"] == 0
    assert len(first["colors"]["drift"]) == 2
    assert first["applied"] is None

    assert sync.main(["--apply", *args]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["ok"] is True
    assert applied["applied"]["colors"] == {"updated": 0, "created": 2}

    assert sync.main(["--check", *args]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["ok"] is True
    assert second["colors"]["drift"] == []
    assert second["colors"]["checked"] == 2


# ─── Безразмерный артикул ────────────────────────────────────────────────────


URN_NAME = "Урны, комплект 2 шт (корпус + крышка)"


def urn_product(*, mode: str = "manual", qph: dict | None = None) -> dict:
    return product(
        sku="урны",
        name=URN_NAME,
        mode=mode,
        # Форма T-380: оба ключа есть, неактивный — null.
        qph={"default": {"auto": None, "manual": 8}} if qph is None else qph,
        lengths=[],
    )


def test_dimensionless_product_is_created_with_default_norm(tmp_path: Path) -> None:
    db_path = tmp_path / "ekranchik.db"
    make_db(db_path).close()

    drift, skipped, creations = sync.compute_drift(
        [urn_product()], [], targets(tmp_path)
    )

    assert drift == []
    assert skipped == []
    assert len(creations) == 1
    assert creations[0]["name"] == "урны"
    assert creations[0]["length"] is None
    assert creations[0]["n"] == 8

    result = sync.apply_drift(db_path, drift, creations, targets(tmp_path))

    assert result is not None
    assert result["created"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "select name, description, length, quantity_per_hanger from profiles"
        ).fetchone()
    finally:
        conn.close()
    assert row == (
        "урны",
        URN_NAME,
        None,
        8,
    )


def test_dimensionless_profile_without_norm_gets_quantity_drift(tmp_path: Path) -> None:
    drift, skipped, creations = sync.compute_drift(
        [urn_product()],
        [profile(name="урны", n=None, length=None, description=URN_NAME)],
        targets(tmp_path),
    )

    assert creations == []
    assert skipped == []
    assert len(drift) == 1
    assert drift[0]["field"] == "quantity_per_hanger"
    assert drift[0]["old"] is None
    assert drift[0]["new"] == 8


def test_dimensionless_default_norm_falls_back_to_auto() -> None:
    """T-380 пишет оба ключа: берём ключ режима, затем второй непустой."""
    real_form = {"default": {"auto": None, "manual": 8}}
    assert sync.default_n(urn_product(mode="manual", qph=real_form)) == 8
    assert sync.default_n(urn_product(mode="auto", qph=real_form)) == 8
    assert sync.default_n(
        urn_product(mode="auto", qph={"default": {"auto": 6, "manual": 8}})
    ) == 6
    assert sync.default_n(
        urn_product(mode="manual", qph={"default": {"auto": 6, "manual": None}})
    ) == 6
    assert sync.default_n(urn_product(qph={"default": {}})) is None
    assert sync.default_n(urn_product(qph={})) is None


def test_dimensionless_product_without_default_norm_stays_as_before(tmp_path: Path) -> None:
    drift, skipped, creations = sync.compute_drift(
        [urn_product(qph={})],
        [profile(name="урны", n=None, length=None, description=URN_NAME)],
        targets(tmp_path),
    )

    assert drift == []
    assert skipped == []
    assert creations == []


def test_length_product_norm_and_creation_are_unchanged(tmp_path: Path) -> None:
    normal = product()
    drift, skipped, creations = sync.compute_drift(
        [normal], [profile(description="Шланг X")], targets(tmp_path)
    )
    assert drift == []
    assert skipped == []
    assert creations == []

    drift, skipped, creations = sync.compute_drift([normal], [], targets(tmp_path))
    assert drift == []
    assert skipped == []
    assert creations[0]["length"] == 2000.0
    assert creations[0]["n"] == 10
