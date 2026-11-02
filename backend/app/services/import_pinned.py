"""Защищённые оригиналы импортов (#288 п.6).

«План февраль 26 02» — единственный экземпляр исходного плана заказчика, на
котором стоит разбор #279 и регрессия на реальном файле. В dev-хранилище файл
лежит в ``imports/`` как ``<sha256>.xls``, но строки ``import_files`` под ним
нет (её снёс старый ``cleanup_seeder`` — корень сирот по ревью R-06). ПРАВИЛО:
байты защищённого оригинала не удаёт ни одна автоматическая ветка (seeder,
«Очистить», TRUNCATE, snapshot-restore, фоновая уборка), а запись ему
возвращает штатный ``db:seed`` — тогда «Скачать» работает по ``file_id``, а не
перебором содержимого каталога.

Файл опознаётся по префиксу sha256: имя на диске — это и есть полный sha256
содержимого (так его пишет ``_get_or_create_import_file``), поэтому префикс
однозначно указывает на экземпляр. Полный sha в репозиторий не кладём — сам
файл данные заказчика, вне git.

Модуль намеренно без зависимостей от ``settings``/ORM/asyncpg: его читают и
async-сервисы, и standalone-скрипт ``scripts/db_snapshot.py``.
"""
from __future__ import annotations

from pathlib import PurePath

#: Защищённые оригиналы: ``(sha256_префикс, расширение, имя для показа)``.
#: ``f52c4369`` — «01-09.2026_01_Упаковочная карта (план РП).xlsx.xls», лист 7
#: «План февраль 26 02» (регрессия #279/#330, см.
#: ``tests/test_plan_import_real_february_sheet.py``).
PINNED_IMPORT_ORIGINALS: tuple[tuple[str, str, str], ...] = (
    (
        "f52c4369",
        ".xls",
        "01-09.2026_01_Упаковочная карта (план РП).xlsx.xls",
    ),
)

#: Префиксы sha256 защищённых оригиналов (для SQL ``LIKE 'префикс%'``).
PINNED_SHA_PREFIXES: tuple[str, ...] = tuple(
    prefix for prefix, _ext, _name in PINNED_IMPORT_ORIGINALS
)


def is_pinned_sha(file_sha256: str | None) -> bool:
    """Защищённый ли это файл по sha256 (полному или префиксу из имени)."""
    if not file_sha256:
        return False
    sha = file_sha256.lower()
    return any(sha.startswith(prefix) for prefix in PINNED_SHA_PREFIXES)


def is_pinned_stored_path(stored_path: str | PurePath | None) -> bool:
    """Защищённый ли файл по пути: имя без расширения = sha256 из ``imports/``."""
    if not stored_path:
        return False
    return is_pinned_sha(PurePath(str(stored_path)).stem)
