"""Копирование файлов фото без лишней перезаписи (#404).

``shutil.copy2`` всегда перезаписывает приёмник и обновляет ``mtime``, даже
если байты не изменились. А версия фото в URL считается по ``mtime_ns +
size``: после повторного импорта того же ZIP менялись бы версии **всех**
фото, и браузер перекачивал бы весь каталог. Поэтому копируем только при
реальном изменении содержимого.
"""

from __future__ import annotations

import filecmp
import shutil
from pathlib import Path


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
    shutil.copy2(source, destination)
    return True
