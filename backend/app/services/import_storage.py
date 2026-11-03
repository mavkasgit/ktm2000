"""Жизненный цикл файла импорта (#288): файл живёт ровно столько, сколько запись.

Правила, которые здесь сторожат:

* **записи нет — файла нет**: ``import_files`` строка удалена и транзакция
  зафиксирована — байты из ``<STORAGE_ROOT>/imports`` уходят в тот же шаг;
* **запись есть — файл скачивается всегда**: скрытие («Убрать из списка»,
  ADR-0056) записи не трогает, поэтому и файл остаётся; живой импорт не
  удаляется ни при каком возрасте;
* **сирота без записи сутки и дольше** убирается автоматически (sweep), с
  отчётом. Порог нужен потому, что файл ложится на диск раньше, чем строка
  встаёт в базу (``plan_import_service._get_or_create_import_file``): уборка
  в ту же секунду съела бы свежий импорт.

Механика «удаление записи → удаление файла» — одна на все точки стирания
строк (delete/force-delete/discard батча, cleanup-сидер, reset-all,
выборочный cleanup): удаляющая сторона вызывает
:func:`schedule_import_file_purge` в своей транзакции, а сами файлы
стираются из event-слушателя коммита сессии. Так не приходится трогать
места коммита (они у всех разные: ручка, CLI-сид, сеедер демо-доски), и
откат транзакции отменяет purge — запись выжила, файл выжил.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import event, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.core.config import settings
from app.models.imports import ImportFile
from app.services.import_pinned import (
    PINNED_IMPORT_ORIGINALS,
    PINNED_SHA_PREFIXES,
    is_pinned_stored_path,
)

logger = logging.getLogger(__name__)

#: Ключ очереди путей в ``Session.info``: пути файлов, чьи строки удалены в
#: этой транзакции. Пустой/отсутствующий ключ — ничего делать не нужно.
_PENDING_PURGE_KEY = "import_files_pending_purge"


def schedule_import_file_purge(db: AsyncSession, paths: Iterable[str | None]) -> None:
    """Запомнить файлы, чьи записи удаляются в текущей транзакции.

    Удаление байтов происходит не здесь, а на коммите (см. слушатели ниже):
    пока транзакция может откатиться, файл обязан остаться — «запись есть —
    файл скачивается всегда» сильнее симметричного правила.
    """
    queue: set[str] = db.info.setdefault(_PENDING_PURGE_KEY, set())
    for path in paths:
        if path:
            queue.add(path)


def take_pending_purge(session: SyncSession) -> set[str]:
    """Извлечь и очистить очередь (вызывается только слушателями событий)."""
    pending = session.info.pop(_PENDING_PURGE_KEY, None)
    return set(pending) if pending else set()


async def collect_recorded_import_paths(db: AsyncSession) -> set[str]:
    """Все ``stored_path`` из ``import_files`` — снимок «какие файлы под записями».

    Используется точками массового стирания строк (reset-all, cleanup-сидер,
    выборочный cleanup): снял набор до удаления — тот же набор уходит с
    байтами после коммита.
    """
    rows = await db.execute(
        select(ImportFile.stored_path).where(ImportFile.stored_path.is_not(None))
    )
    return {path for path in rows.scalars().all() if path}


def remove_import_files_sync(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    """Удалить файлы с диска. Идемпотентно: отсутствующий файл — не ошибка.

    Возвращает ``(removed, failed)``. ``FileNotFoundError`` считается
    успешным удалением (файла и так нет — правило выполнено), прочие OSError
    — в ``failed``: сбой unlink не должен ронять уже закоммиченную ручку
    (на Windows файл может держать открытое скачивание; такие случаи добирает
    sweep по суточному порогу).
    """
    removed: list[str] = []
    failed: list[str] = []
    for path in sorted(set(paths)):
        try:
            Path(path).unlink(missing_ok=True)
            removed.append(path)
        except OSError as exc:
            logger.warning("Не удалось удалить импорт-файл %s: %s", path, exc)
            failed.append(path)
    return removed, failed


def _purge_reported_paths(paths: set[str], origin: str) -> None:
    if not paths:
        return
    # #288 п.6: защищённые оригиналы (лист «План февраль 26 02») не удаёт ни
    # одна автоматическая ветка — seeder/«Очистить»/TRUNCATE/snapshot-restore.
    # Запись им вернёт штатный db:seed; байты — единственный экземпляр #279.
    purgeable = {path for path in paths if not is_pinned_stored_path(path)}
    skipped = len(paths) - len(purgeable)
    if skipped:
        logger.info(
            "#288 %s: защищённых оригиналов не тронуто: %d", origin, skipped
        )
    if not purgeable:
        return
    removed, failed = remove_import_files_sync(purgeable)
    logger.info(
        "#288 %s: удалено импорт-файлов без записи: %d; сбоев: %d; список: %s",
        origin,
        len(removed),
        len(failed),
        "; ".join(removed),
    )


@event.listens_for(SyncSession, "after_commit")
def _purge_after_commit(session: SyncSession) -> None:
    """COMMIT сессии — в бою это фиксация транзакции запроса/сидера.

    Здесь же срабатывает и ``db.commit()`` внутри тестового харнесса:
    ``tests/conftest.py`` с ``join_transaction_mode="create_savepoint"``
    держит внешнюю транзакцию на *коннекте*, а сессионный корневой
    SessionTransaction при коммите отдаёт SAVEPOINT и штатно вызывает
    ``after_commit`` (проверено на исходниках SQLAlchemy 2.1:
    ``SessionTransaction.commit`` диспатчит событие и для корневой
    транзакции с ``should_commit``-соединением). Откат коннекта в teardown
    файлов не возвращает — тест, проверяющий «удаление снесло файл», видит
    то же поведение, что и прод.
    """
    _purge_reported_paths(take_pending_purge(session), "после commit")


def _discard_pending(session: SyncSession, *_: Any) -> None:
    """Откат: строки живы, файлы не трогаем, очередь сбрасываем."""
    session.info.pop(_PENDING_PURGE_KEY, None)


event.listen(SyncSession, "after_rollback", _discard_pending)
event.listen(SyncSession, "after_soft_rollback", _discard_pending)


class SweepReport:
    """Итог одной уборки каталога ``imports/``."""

    def __init__(self) -> None:
        self.scanned: int = 0
        self.removed: list[str] = []
        #: Сироты моложе порога — всегда сохраняются.
        self.kept_young: list[str] = []
        #: Файлы под живыми записями — не удаляются ни при каком возрасте.
        self.kept_recorded: int = 0
        #: Защищённые оригиналы (#288 п.6) — не удаляются ни при каком возрасте
        #: и ни при каком наличии записи.
        self.kept_pinned: int = 0
        #: Сбои unlink (файл держит открытое скачивание и т.п.) — добирает
        #: следующий проход sweep после порога.
        self.failed: list[str] = []

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "removed": list(self.removed),
            "kept_young": list(self.kept_young),
            "kept_recorded": self.kept_recorded,
            "kept_pinned": self.kept_pinned,
            "failed": list(self.failed),
        }

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} removed={len(self.removed)} "
            f"kept_young={len(self.kept_young)} kept_recorded={self.kept_recorded} "
            f"kept_pinned={self.kept_pinned} failed={len(self.failed)}"
        )


def _normalize_path(path: str | os.PathLike[str]) -> str:
    """Канон для сравнения: абсолют, без «.»/«..», регистр как на диске.

    ``stored_path`` пишется в момент импорта относительно CWD процесса
    (``STORAGE_ROOT=../data/storage-dev`` — путь от ``backend/``). listing
    каталога даёт ту же форму, если процесс сидит там же; нормализация через
    ``realpath`` уравнивает и случай относительного/абсолютного написания.
    Для несуществующего пути ``realpath`` (strict=False по умолчанию) тоже
    даёт корректный абсолют.
    """
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _files_in_import_dir() -> list[Path]:
    directory = Path(settings.IMPORT_STORAGE_DIR)
    if not directory.is_dir():
        return []
    return [entry for entry in directory.iterdir() if entry.is_file()]


async def sweep_orphan_import_files(
    db: AsyncSession, *, ttl_hours: float | None = None
) -> SweepReport:
    """Убрать из ``imports/`` файлы без строки в ``import_files`` старше порога.

    * файлы **под записью** не удаляются никогда, сколько бы ни лежали;
    * сироты **моложе порога** (по mtime: файл создан раньше строки — свежий
      импорт ещё может вставать в базу) не удаляются;
    * всё остальное удаляется, отчёт — в возвращаемом ``SweepReport``
      (CLI печатает его, планировщик пишет в лог).

    Удаляются только файлы каталога ``imports/`` — другие подкаталоги
    хранилища (products, backups) здесь не трогаются в принципе.
    """
    report = SweepReport()
    ttl = timedelta(
        hours=(ttl_hours if ttl_hours is not None else settings.IMPORT_ORPHAN_TTL_HOURS)
    )
    files = _files_in_import_dir()
    if not files:
        return report

    recorded = await collect_recorded_import_paths(db)
    recorded_norm = {_normalize_path(p) for p in recorded}
    cutoff = (datetime.now(UTC) - ttl).timestamp()

    orphan_candidates: list[str] = []
    for entry in files:
        report.scanned += 1
        # Защищённый оригинал (#288 п.6) не удаляется уборкой никогда — даже
        # если строка import_files под ним по какой-то причине пропала.
        if is_pinned_stored_path(entry):
            report.kept_pinned += 1
            continue
        if _normalize_path(entry) in recorded_norm:
            # Живой импорт: «запись есть — файл скачивается всегда».
            report.kept_recorded += 1
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError as exc:
            report.failed.append(str(entry))
            logger.warning("Sweep: не удалось прочитать mtime %s: %s", entry, exc)
            continue
        if mtime > cutoff:
            report.kept_young.append(str(entry))
            continue
        orphan_candidates.append(str(entry))

    if orphan_candidates:
        removed, failed = await asyncio.to_thread(
            remove_import_files_sync, orphan_candidates
        )
        report.removed = removed
        report.failed.extend(failed)
        logger.info(
            "#288 sweep imports/: удалено сирот старше %s ч: %d; список: %s",
            ttl.total_seconds() / 3600,
            len(removed),
            "; ".join(removed),
        )
    return report


def pinned_rows_clause():
    """SQL-условие «строка import_files — защищённый оригинал» (#288 п.6).

    Возвращает ``OR(file_sha256 LIKE 'префикс%', …)``. Точки массового стирания
    строк (cleanup-сидер) обязаны добавлять ``~pinned_rows_clause()``, чтобы не
    снести запись единственного экземпляра; байты дополнительно сторожит
    :func:`_purge_reported_paths`.
    """
    if not PINNED_SHA_PREFIXES:
        return false()
    return or_(*[ImportFile.file_sha256.like(f"{prefix}%") for prefix in PINNED_SHA_PREFIXES])


def _pinned_content_type(extension: str) -> str:
    return {
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(extension.lower(), "application/octet-stream")


async def restore_pinned_import_records(
    db: AsyncSession,
) -> list[ImportFile]:
    """Вернуть запись ``import_files`` защищённым оригиналам с диска (#288 п.6).

    Идемпотентно и безопасно на чужих машинах: файл заказчика лежит только в
    dev-хранилище владельца, поэтому если файла на диске нет — функция молча
    пропускает (не создаёт битую запись в никуда). Если строка под файлом уже
    есть — тоже ничего не делает. Возвращает список СОЗДАННЫХ строк.

    Вызывается штатным ``db:seed`` (``run_full_seed``) после cleanup-шага:
    «db:seed --force»/snapshot-restore могли стереть запись, а байты
    защищённого оригинала не трогались — здесь запись возвращается, и «Скачать»
    снова работает по ``file_id``, а не перебором каталога.
    """
    # Ленивый импорт: excel_import — парсер, он не нужен на пути обычной
    # уборки/purge, и так избегаем любого порядка импорта при регистрации
    # слушателей в main.lifespan.
    from app.services.excel_import import (
        detect_workbook_format,
        validate_excel_extension,
    )

    storage_dir = Path(settings.IMPORT_STORAGE_DIR)
    created: list[ImportFile] = []
    for prefix, _declared_ext, display_name in PINNED_IMPORT_ORIGINALS:
        existing = (
            await db.execute(
                select(ImportFile).where(ImportFile.file_sha256.like(f"{prefix}%"))
            )
        ).scalars().first()
        if existing is not None:
            continue
        if not await asyncio.to_thread(storage_dir.is_dir):
            continue
        match = await asyncio.to_thread(
            lambda: next(
                (p for p in storage_dir.glob(f"{prefix}*") if p.is_file()), None
            )
        )
        if match is None:
            # Файла на этой машине нет — нечего и возвращать.
            continue
        content = await asyncio.to_thread(match.read_bytes)
        # Имя файла на диске — полный sha256 содержимого (так его пишет
        # ``_get_or_create_import_file``). Берём sha из имени, сверяя с
        # фактическим содержимым: при расхождении доверяем имени (оно и есть
        # канонический ключ хранилища), иначе дедуп по хешу разъедется с файлом.
        stem_sha = match.stem.lower()
        actual_sha = hashlib.sha256(content).hexdigest()
        file_sha256 = stem_sha if stem_sha.startswith(prefix) else actual_sha
        extension = validate_excel_extension(display_name)
        import_file = ImportFile(
            original_filename=display_name,
            stored_path=str(match),
            content_type=_pinned_content_type(extension),
            file_extension=extension,
            detected_format=detect_workbook_format(content, display_name),
            file_sha256=file_sha256,
            size_bytes=len(content),
        )
        db.add(import_file)
        created.append(import_file)
    if created:
        await db.flush()
        logger.info(
            "#288: возвращено записей защищённых оригиналов: %d (%s)",
            len(created),
            "; ".join(f.original_filename for f in created),
        )
    return created
