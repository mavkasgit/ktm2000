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

from pathlib import Path

from app.core.config import settings


def photo_file_version(path: str | None) -> str | None:
    """Версия файла фото или ``None``, если пути нет или файл недоступен.

    ``path`` хранится от корня storage (``products/<файл>``, ADR-0026), но
    старые/ручные записи могут быть абсолютными — поддерживаются оба вида.
    """
    if not path:
        return None

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(settings.STORAGE_ROOT) / candidate

    try:
        stat = candidate.stat()
    except OSError:
        # Файла нет — версии тоже нет. Фронт просто не добавит `?v=`;
        # отдельного 500 из-за отсутствующей картинки быть не должно.
        return None

    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
