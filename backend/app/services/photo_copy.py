"""Копирование файлов фото без лишней перезаписи (#404).

``shutil.copy2`` всегда перезаписывает приёмник и обновляет ``mtime``, даже
если байты не изменились. А версия фото в URL считается по ``mtime_ns +
size``: после повторного импорта того же ZIP менялись бы версии **всех**
фото, и браузер перекачивал бы весь каталог. Поэтому копируем только при
реальном изменении содержимого.

Обратная ловушка: ``copy2`` переносит ``mtime`` из ZIP, поэтому разные байты
одинакового размера с одинаковым timestamp дали бы ту же версию. После
реального копирования выставляем приёмнику текущее время — версия меняется
гарантированно.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import time
from pathlib import Path


def _next_mtime_ns(previous_ns: int | None) -> int:
    """Текущее время в ns, строго больше прежнего mtime приёмника.

    Часы с грубым разрешением (или копирование в ту же наносекунду) не должны
    оставить версию прежней — иначе замена фото не сбросит кэш.
    """
    now_ns = time.time_ns()
    if previous_ns is not None and now_ns <= previous_ns:
        return previous_ns + 1
    return now_ns


def copy_photo_if_changed(src: str | Path, dst: str | Path) -> bool:
    """Скопировать фото, только если содержимое отличается.

    Возвращает ``True``, если файл был скопирован (версия изменится), и
    ``False``, если приёмник уже содержит те же байты (``mtime``/версия
    остаются прежними). ``shallow=False`` сравнивает содержимое, а не только
    метаданные: ZIP-импорт каждый раз даёт новый ``mtime`` у источника.
    """
    source = Path(src)
    destination = Path(dst)
    if destination.exists() and filecmp.cmp(source, destination, shallow=False):
        return False

    previous_mtime_ns = (
        destination.stat().st_mtime_ns if destination.exists() else None
    )
    shutil.copy2(source, destination)
    next_mtime_ns = _next_mtime_ns(previous_mtime_ns)
    os.utime(destination, ns=(next_mtime_ns, next_mtime_ns))
    return True
