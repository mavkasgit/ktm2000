"""Версия файла фото для cache-busting URL (#404).

Фото лежат в storage и отдаются по стабильному ``/static/products/<файл>``,
а nginx ставит на ``/static/`` долгий ``Cache-Control: immutable``. Чтобы
замена файла была видна без ``Ctrl+F5``, URL конкретного фото получает
``?v=<версия>``. Версия считается из файла при сериализации ответа, а не
запоминается в БД при загрузке: только так она меняется и тогда, когда файл
заменили мимо API (sync, скрипт, ручное копирование в storage).

``mtime_ns + size`` — дешёвая пара без чтения содержимого: списки артикулов
сериализуются часто, а хэш каждого файла на каждый запрос был бы дороже
самого ответа. Ограничение известно и принято: замена с сохранением и mtime,
и размера версию не сдвинет (ADR-0026, issue #404).
"""

from __future__ import annotations

import logging
import re
import stat as stat_module
from collections.abc import Iterable
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_STATIC_PREFIXES = ("/static/", "static/")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:/")


def _resolve_storage_path(path: str) -> Path | None:
    """Путь файла внутри ``STORAGE_ROOT`` или ``None`` для недопустимого пути.

    Канон ADR-0026 — путь **относительно** корня storage
    (``products/<файл>``). Дополнительно принимаются URL-пути
    ``/static/products/<файл>`` (так фото приходит из API/старых записей) и
    ``\\``-разделители Windows.

    Абсолютный путь (``C:\\...``, ``/app/storage/...``) не резолвится: он
    зависит от машины/контейнера и может указать мимо корня. Такой путь
    логируется и версии не получает — ``stat`` по чужому файлу не делаем.
    """
    raw = path.strip().replace("\\", "/")
    if not raw or "://" in raw:
        # Внешний URL — не файл storage. Его версию источник не отдаёт.
        return None

    for prefix in _STATIC_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    if raw.startswith("/") or _WINDOWS_ABSOLUTE.match(raw):
        logger.warning(
            "photo path is absolute, expected storage-relative path: %r (ADR-0026)",
            path,
        )
        return None

    relative = Path(raw)
    if any(part == ".." for part in relative.parts):
        logger.warning("photo path escapes storage root: %r", path)
        return None

    return Path(settings.STORAGE_ROOT) / relative


def photo_file_version(path: str | None) -> str | None:
    """Версия файла фото или ``None``, если пути нет или файл недоступен.

    ``path`` — путь от ``STORAGE_ROOT`` (``products/<файл>``, ADR-0026);
    ``/static/products/<файл>`` и ``\\``-разделители нормализуются. Версия —
    ``mtime_ns-size`` в hex, чтобы URL оставался коротким.
    """
    if not path:
        return None

    candidate = _resolve_storage_path(path)
    if candidate is None:
        return None

    try:
        file_stat = candidate.stat()
    except OSError as exc:
        # Отдельного 500 из-за отсутствующей картинки быть не должно: фронт
        # просто не добавит `?v=`. Но и молчать нельзя — битая ссылка в БД
        # должна быть видна в логах.
        logger.warning("photo file is unavailable: path=%r (%s)", path, exc)
        return None

    if not stat_module.S_ISREG(file_stat.st_mode):
        logger.warning("photo path is not a regular file: path=%r", path)
        return None

    return f"{file_stat.st_mtime_ns:x}-{file_stat.st_size:x}"


def photo_file_versions(
    pairs: Iterable[tuple[str | None, str | None]],
) -> list[tuple[str | None, str | None]]:
    """Версии для пар ``(thumb_path, full_path)`` одним вызовом.

    Синхронная функция: route-слой зовёт её через ``asyncio.to_thread``, чтобы
    ``stat`` не блокировал event loop. Для списка это один переход в поток на
    весь ответ, а не по два ``stat`` на каждый товар в цикле.
    """
    return [(photo_file_version(thumb), photo_file_version(full)) for thumb, full in pairs]
