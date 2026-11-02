"""Жизненный цикл файла импорта (#288): «запись есть — файл живёт, записи нет — файла нет».

Закрывает чек-лист «Приёмка» тикета #288 по пунктам, плюс риск из ревью R-06
(откатанный/сиротский файл не должен съедаться TTL'ом, если под ним есть
запись). Тесты работают на РЕАЛЬНЫХ байтах в ``settings.IMPORT_STORAGE_DIR``
(per-run/per-worker temp-каталог из conftest), поэтому проверяют именно диск, а
не только строки БД. Порог «сутки» подкручивается mtime файла, а не ожиданием.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import date
from pathlib import Path

from app.core.config import settings
from app.models.imports import (
    ImportBatch,
    ImportBatchMode,
    ImportBatchStatus,
    ImportFile,
)
from app.models.production_plan import (
    ProductionPlan,
    ProductionPlanStatus,
)
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
from app.services.import_pinned import PINNED_IMPORT_ORIGINALS
from app.services.import_storage import (
    remove_import_files_sync,
    restore_pinned_import_records,
    schedule_import_file_purge,
    sweep_orphan_import_files,
)
from sqlalchemy.ext.asyncio import AsyncSession

# asyncio-режим в pytest.ini = AUTO, явный маркер не нужен: он бы ругался на
# синхронный тест _purge_wiped_import_files ниже.

#: Как в conftest: относительный путь STORAGE_ROOT резолвится от cwd=backend,
#: но ``settings.IMPORT_STORAGE_DIR`` уже абсолютный/рабочий для процесса теста.
IMPORTS_DIR = Path(settings.IMPORT_STORAGE_DIR)


def _content(tag: str) -> bytes:
    return f"ktm2000-#288 fake workbook bytes::{tag}".encode("utf-8")


def _path_for(sha: str, ext: str = ".xlsx") -> Path:
    return IMPORTS_DIR / f"{sha}{ext}"


def _write_bytes(tag: str, *, ext: str = ".xlsx", age_hours: float | None = None) -> tuple[str, Path]:
    """Положить байты в imports/ как это делает импорт (<sha><ext>). Вернуть (sha, путь)."""
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    content = _content(tag)
    sha = hashlib.sha256(content).hexdigest()
    path = _path_for(sha, ext)
    path.write_bytes(content)
    if age_hours is not None:
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
    return sha, path


async def _add_record(
    session: AsyncSession, *, sha: str, path: Path, ext: str = ".xlsx"
) -> ImportFile:
    row = ImportFile(
        original_filename=f"{sha[:8]}{ext}",
        stored_path=str(path),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=ext,
        detected_format="zip-workbook",
        file_sha256=sha,
        size_bytes=len(_content(sha)),
    )
    session.add(row)
    await session.flush()
    return row


async def _make_plan(session: AsyncSession, tag: str) -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN288-{tag}", name=f"P {tag}", status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_batch(session: AsyncSession, plan: ProductionPlan, file: ImportFile) -> ImportBatch:
    batch = ImportBatch(
        source_file_id=file.id, production_plan_id=plan.id, mode=ImportBatchMode.create_plan,
        status=ImportBatchStatus.parsed, sheet_name="План", header_row_number=1,
        total_rows=1, parsed_rows=1, summary={},
    )
    session.add(batch)
    await session.flush()
    return batch


# --- Приёмка п.1: «Удалить» сносит байты и не оставляет огрызков ------------


async def test_delete_removes_bytes_from_disk_and_leaves_no_crumbs(
    session: AsyncSession, client
) -> None:
    sha, path = _write_bytes("del-1", age_hours=100)  # давно лежит — не «свежий»
    plan = await _make_plan(session, "del-1")
    file = await _add_record(session, sha=sha, path=path)
    batch = await _make_batch(session, plan, file)
    await session.commit()
    assert path.exists()

    resp = await client.delete(f"/api/production-plans/{plan.id}/batches/{batch.id}")
    assert resp.status_code == 200, resp.text

    # Строка ушла — ушли и байты; ни `<sha>`, ни `<sha>.tmp`, ни соседних
    # расширений не осталось (импорт пишет один файл <sha><ext> без tmp-фазы).
    assert (await session.get(ImportFile, file.id)) is None
    assert not path.exists()
    assert list(IMPORTS_DIR.glob(f"{sha}*")) == []


# --- Приёмка п.2: «Убрать из списка» оставляет запись+файл, скрытый качается --


async def test_hide_keeps_record_and_file_and_downloads(session: AsyncSession, auth_client) -> None:
    sha, path = _write_bytes("hide-1")
    plan = await _make_plan(session, "hide-1")
    file = await _add_record(session, sha=sha, path=path)
    batch = await _make_batch(session, plan, file)
    await session.commit()

    hide = await auth_client.post(
        f"/api/production-plans/{plan.id}/batches/{batch.id}/hide"
    )
    assert hide.status_code == 200, hide.text

    # Скрытие — не удаление: и запись, и файл целы.
    assert path.exists()
    assert (await session.get(ImportFile, file.id)) is not None

    # Скрытый импорт скачивается штатной кнопкой (по file_id, не перебором каталога).
    download = await auth_client.get(f"/api/imports/files/{file.id}/download")
    assert download.status_code == 200, download.text
    assert download.content == _content("hide-1")


# --- Приёмка п.3: уборка берёт сирот старше порога, только imports/ ----------


async def test_sweep_removes_old_orphan_keeps_young_and_recorded(session: AsyncSession) -> None:
    # (a) сирота без записи старше суток — удаляется
    old_sha, old_path = _write_bytes("old-orphan", age_hours=48)
    # (b) сирота моложе порога — не трогается (гонка: байты раньше строки)
    fresh_sha, fresh_path = _write_bytes("fresh-orphan", age_hours=0)
    # (c) живой импорт под записью, сколько бы ни лежал — не трогается (п.4)
    rec_sha, rec_path = _write_bytes("recorded", age_hours=1000)
    await _add_record(session, sha=rec_sha, path=rec_path)
    # (d) файл в соседнем каталоге хранилища — вне зоны sweep (только imports/)
    sibling = Path(settings.STORAGE_ROOT) / "products" / "keep-me.bin"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_bytes(b"not an import")
    await session.commit()

    report = await sweep_orphan_import_files(session, ttl_hours=24)

    assert not old_path.exists()          # старый сирота удалён
    assert fresh_path.exists()            # младше порога — цел
    assert rec_path.exists()              # под записью — цел
    assert sibling.exists()               # не из imports/ — не тронут
    assert str(old_path) in report.removed
    assert str(fresh_path) in report.kept_young
    assert report.kept_recorded >= 1


# --- Приёмка п.4: живой импорт (есть запись) не удаляется никогда ------------


async def test_recorded_file_never_swept_regardless_of_age(session: AsyncSession) -> None:
    sha, path = _write_bytes("alive", age_hours=24 * 365 * 5)  # 5 лет под записью
    await _add_record(session, sha=sha, path=path)
    await session.commit()

    report = await sweep_orphan_import_files(session)

    assert path.exists()
    assert str(path) not in report.removed


# --- Приёмка п.5: cleanup-сидер (db:seed --force / «Очистить») без сирот ------


async def test_cleanup_seeder_removes_bytes_of_doomed_records(session: AsyncSession) -> None:
    """`db:seed --force` / «Очистить» не оставляет сирот (приёмка п.5).

    ``clear_generated_production_data`` сносит и батчи, и строки ``import_files``
    (сначала ``import_batches``, поэтому под батчем строка тоже обречена). #288:
    вместе с КАЖДОЙ стёртой строкой уходит и байт — в каталоге не остаётся
    ни одного файла без записи.
    """
    dead_sha, dead_path = _write_bytes("seed-orphan", age_hours=100)
    await _add_record(session, sha=dead_sha, path=dead_path)

    # Живой импорт под батчем: cleanup сносит батч → строка и файл обречены.
    live_sha, live_path = _write_bytes("seed-live", age_hours=100)
    plan = await _make_plan(session, "seed-live")
    live_file = await _add_record(session, sha=live_sha, path=live_path)
    await _make_batch(session, plan, live_file)
    await session.commit()
    assert dead_path.exists() and live_path.exists()

    await clear_generated_production_data(session)
    await session.commit()  # коммит триггерит after_commit-purge

    # Обе строки стёрты — обе пары байтов ушли с ними (сирот нет).
    for sha in (dead_sha, live_sha):
        assert (await session.execute(_select_by_sha(sha))).scalar_one_or_none() is None
    assert not dead_path.exists()
    assert not live_path.exists()
    # Ни одного осиротевшего файла этих импортов в каталоге не осталось.
    assert list(IMPORTS_DIR.glob(f"{dead_sha}*")) == []
    assert list(IMPORTS_DIR.glob(f"{live_sha}*")) == []


def _select_by_sha(sha: str):
    from sqlalchemy import select

    return select(ImportFile).where(ImportFile.file_sha256 == sha)


# --- Приёмка п.6: защищённый оригинал «План февраль 26 02» --------------------


async def test_restore_pinned_creates_record_and_download_works(session: AsyncSession, auth_client) -> None:
    prefix, ext, display_name = PINNED_IMPORT_ORIGINALS[0]
    # Кладём байты защищённого оригинала как сироту (записи нет — состояние из тикета).
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    sha = prefix + hashlib.sha256(b"february").hexdigest()[len(prefix):]
    path = IMPORTS_DIR / f"{sha}{ext}"
    # содержимое не обязано совпадать с sha (имя = sha); важно, что stem начинается с prefix
    path.write_bytes(b"february-only-original")

    created = await restore_pinned_import_records(session)
    await session.commit()

    assert len(created) == 1
    row = created[0]
    assert row.stored_path == str(path)
    assert row.original_filename == display_name
    assert row.file_sha256.lower().startswith(prefix)

    # Идемпотентно: второй вызов ничего не добавляет.
    assert await restore_pinned_import_records(session) == []

    # Достаётся штатной кнопкой по file_id, а не перебором каталога.
    download = await auth_client.get(f"/api/imports/files/{row.id}/download")
    assert download.status_code == 200, download.text
    assert download.content == b"february-only-original"


async def test_pinned_survives_cleanup_and_sweep_and_purge(session: AsyncSession) -> None:
    prefix, ext, _ = PINNED_IMPORT_ORIGINALS[0]
    sha = prefix + "a" * (64 - len(prefix))
    path = IMPORTS_DIR / f"{sha}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"only original")
    row = await _add_record(session, sha=sha, path=path, ext=ext)
    # очень старый — иначе бы сироту sweep съел
    old = time.time() - 400 * 3600
    os.utime(path, (old, old))
    await session.commit()

    # 1) cleanup-сидер не сносит защищённую строку (нет батча, но исключена).
    await clear_generated_production_data(session)
    await session.commit()
    assert (await session.get(ImportFile, row.id)) is not None
    assert path.exists()

    # 2) фоновая уборка не трогает защищённый оригинал даже как сироту.
    report = await sweep_orphan_import_files(session)
    assert path.exists()
    assert str(path) not in report.removed
    assert report.kept_pinned >= 1

    # 3) прямой purge (TRUNCATE/snapshot-restore очередь) пропускает защищённый.
    schedule_import_file_purge(session, [str(path)])
    await session.commit()
    assert path.exists()


# --- Риск R-06: откатанный/сиротский файл не съедается при наличии записи -----


async def test_cancelled_batch_file_not_orphaned_by_sweep(session: AsyncSession) -> None:
    """Откат оставляет строку батча/файла → файл под записью → sweep не трогает.

    Реальный «красный откат» (rollback_changeset) статусы меняет, а строки не
    удаляет; проверяем суть риска R-06: байты под записью не исчезают по TTL,
    даже если батч откачен/отменён и давно лежит.
    """
    sha, path = _write_bytes("rolled", age_hours=200)
    plan = await _make_plan(session, "rolled")
    await _add_record(session, sha=sha, path=path)
    batch = await _make_batch(session, plan, await _first_file(session, sha))
    batch.status = ImportBatchStatus.cancelled  # «откатанный»
    await session.commit()

    report = await sweep_orphan_import_files(session, ttl_hours=24)
    assert path.exists()
    assert str(path) not in report.removed


async def _first_file(session: AsyncSession, sha: str) -> ImportFile:
    return (await session.execute(_select_by_sha(sha))).scalar_one()


async def test_remove_import_files_sync_is_idempotent(tmp_path) -> None:
    missing = tmp_path / "nope.xlsx"
    removed, failed = remove_import_files_sync([str(missing)])
    assert removed == [str(missing)]  # «и так нет» = успех, не сбой
    assert failed == []


# --- Приёмка п.5: «Очистить» в панели разработчика (POST /routes-seed/cleanup) --


async def test_developer_panel_cleanup_removes_bytes_no_orphans(
    session: AsyncSession, auth_client
) -> None:
    sha, path = _write_bytes("panel-clean", age_hours=100)
    await _add_record(session, sha=sha, path=path)
    await session.commit()
    assert path.exists()

    resp = await auth_client.post("/api/routes-seed/cleanup", json={"tables": ["import_files"]})
    assert resp.status_code == 204, resp.text

    # Строка стёрта — байт ушёл с ней; огрызков в imports/ не осталось.
    assert (await session.execute(_select_by_sha(sha))).scalar_one_or_none() is None
    assert not path.exists()
    assert list(IMPORTS_DIR.glob(f"{sha}*")) == []


# --- Приёмка п.5: db:snapshot restore убирает файлы стёртых записей ------------


def test_snapshot_restore_purge_removes_wiped_and_keeps_pinned(tmp_path) -> None:
    from scripts.db_snapshot import _purge_wiped_import_files

    prefix, ext, _ = PINNED_IMPORT_ORIGINALS[0]
    gone = tmp_path / "aabbccddeeff.xlsx"  # была запись, после restore её нет → уходит
    gone.write_bytes(b"x")
    kept = tmp_path / "112233445566.xlsx"  # запись жива и после restore → цел
    kept.write_bytes(b"y")
    pinned = tmp_path / f"{prefix}{'a' * (64 - len(prefix))}{ext}"  # защищённый → цел
    pinned.write_bytes(b"only-original")

    removed = _purge_wiped_import_files(
        before={str(gone), str(kept), str(pinned)},
        after={str(kept)},  # restore вернул базу без записей gone и pinned
    )

    assert str(gone) in removed and not gone.exists()
    assert kept.exists() and str(kept) not in removed
    # Защищённый оригинал не трогает даже restore (#288 п.6).
    assert pinned.exists() and str(pinned) not in removed
