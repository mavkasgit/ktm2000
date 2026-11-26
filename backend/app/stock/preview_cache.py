"""Разбор листа остатков один раз на источник (#472).

Предпросмотр импорта остатков раньше принимал файл в каждом запросе: смена
сортировки, поиска или фильтра колонки заново отправляла байты и заново
разбирала xlsx — на листе заказчика это сотни строк и заметная пауза. Здесь
живёт серверный кэш разбора:

* **источник** — содержимое файла (или текста из буфера) под токеном
  ``sha256``; по токену сервер достаёт байты, чтобы разобрать ещё не открытый
  лист того же файла;
* **разобранный лист** — результат ``parse`` + обогащения (артикулы, штуки,
  участок) ключом ``(токен, лист, выбор строк, шаблон)``.

Ключ намеренно не включает фильтры/сортировку/оверрайды: они применяются к
уже разобранным строкам в ``query_remainder_preview_items``. Новый файл даёт
другой ``sha256`` — то есть новый ключ; новый лист — другой ``sheet_index``.

Срок жизни — ``TTL_SECONDS``: разбор держит ссылки на артикулы и участки из
БД, и вечный кэш показывал бы каталог на момент загрузки файла. Память
ограничена числом источников, суммарным весом содержимого и числом строк
разобранных листов, поэтому «5000 строк × несколько файлов» не остаются в
процессе навсегда.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# Источник (файл/буфер) живёт 15 минут: дольше диалог импорта не открыт, а
# каталог за это время меняется редко.
TTL_SECONDS = 15 * 60.0
# Сколько разных источников помнить одновременно.
MAX_SOURCES = 8
# Суммарный вес содержимого источников.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
# Сколько листов одного источника помнить (ОСВ-файлы обычно 1–5 листов).
MAX_SHEETS_PER_SOURCE = 6
# Суммарное число строк разобранных листов по всем источникам.
MAX_PARSED_ROWS = 60_000

SOURCE_KIND_FILE = "file"
SOURCE_KIND_CLIPBOARD = "clipboard"


@dataclass
class _SourceEntry:
    content: bytes
    kind: str
    stored_at: float
    parsed: OrderedDict[tuple, Any] = field(default_factory=OrderedDict)


class RemainderPreviewCache:
    """LRU + TTL кэш разбора источников предпросмотра остатков."""

    def __init__(
        self,
        *,
        ttl_seconds: float = TTL_SECONDS,
        max_sources: int = MAX_SOURCES,
        max_source_bytes: int = MAX_SOURCE_BYTES,
        max_sheets_per_source: int = MAX_SHEETS_PER_SOURCE,
        max_parsed_rows: int = MAX_PARSED_ROWS,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_sources = max_sources
        self._max_source_bytes = max_source_bytes
        self._max_sheets_per_source = max_sheets_per_source
        self._max_parsed_rows = max_parsed_rows
        self._entries: OrderedDict[str, _SourceEntry] = OrderedDict()
        self._parsed_rows = 0
        self._lock = threading.Lock()

    # ── источники ─────────────────────────────────────────────────────────

    @staticmethod
    def token_for(content: bytes) -> str:
        """Токен источника — контентный адрес: другой файл даёт другой ключ."""
        return hashlib.sha256(content).hexdigest()

    def remember_source(self, content: bytes, kind: str) -> str:
        """Запомнить содержимое и вернуть его токен (повтор — тот же токен)."""
        token = self.token_for(content)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            entry = self._entries.get(token)
            if entry is None:
                entry = _SourceEntry(content=content, kind=kind, stored_at=now)
                self._entries[token] = entry
            else:
                entry.stored_at = now
                entry.kind = kind
                self._entries.move_to_end(token)
            self._evict(now)
        return token

    def get_source(self, token: str) -> tuple[bytes, str] | None:
        """Содержимое и род источника по токену; ``None`` — токен протух."""
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            entry = self._entries.get(token)
            if entry is None:
                return None
            entry.stored_at = now
            self._entries.move_to_end(token)
            return entry.content, entry.kind

    # ── разобранные листы ─────────────────────────────────────────────────

    def get_parsed(self, token: str, key: tuple) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if key not in entry.parsed:
                return None
            entry.stored_at = now
            entry.parsed.move_to_end(key)
            self._entries.move_to_end(token)
            return entry.parsed[key]

    def put_parsed(self, token: str, key: tuple, parsed: Any, rows: int) -> None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return
            existing = entry.parsed.get(key)
            if existing is not None:
                self._parsed_rows = max(0, self._parsed_rows - self._rows_of(existing))
            entry.parsed[key] = parsed
            entry.parsed.move_to_end(key)
            self._parsed_rows += rows
            entry.stored_at = now
            while len(entry.parsed) > self._max_sheets_per_source:
                _, dropped = entry.parsed.popitem(last=False)
                self._parsed_rows = max(0, self._parsed_rows - self._rows_of(dropped))
            self._evict(now)

    # ── обслуживание ──────────────────────────────────────────────────────

    @staticmethod
    def _rows_of(parsed: Any) -> int:
        items = getattr(parsed, "items", None)
        return len(items) if isinstance(items, list) else 0

    def _expire(self, now: float) -> None:
        deadline = now - self._ttl
        while self._entries:
            token, entry = next(iter(self._entries.items()))
            if entry.stored_at >= deadline:
                break
            self._drop(token)

    def _evict(self, now: float) -> None:
        while self._entries and (
            len(self._entries) > self._max_sources
            or self._total_bytes() > self._max_source_bytes
            or self._parsed_rows > self._max_parsed_rows
        ):
            token = next(iter(self._entries))
            self._drop(token)

    def _total_bytes(self) -> int:
        return sum(len(entry.content) for entry in self._entries.values())

    def _drop(self, token: str) -> None:
        entry = self._entries.pop(token, None)
        if entry is None:
            return
        self._parsed_rows = max(
            0,
            self._parsed_rows - sum(self._rows_of(parsed) for parsed in entry.parsed.values()),
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._parsed_rows = 0

    def stats(self) -> dict[str, int]:
        """Состояние кэша для тестов и диагностики."""
        with self._lock:
            return {
                "sources": len(self._entries),
                "bytes": self._total_bytes(),
                "parsed_rows": self._parsed_rows,
            }


remainder_preview_cache = RemainderPreviewCache()


def reset_remainder_preview_cache() -> None:
    """Очистить кэш (тестовая изоляция и аварийная инвалидация)."""
    remainder_preview_cache.clear()


def remember_remainder_preview_source(content: bytes, kind: str) -> str:
    return remainder_preview_cache.remember_source(content, kind)


def get_remainder_preview_source(token: str) -> tuple[bytes, str] | None:
    return remainder_preview_cache.get_source(token)


def get_cached_remainder_parsed(token: str, key: tuple) -> Any | None:
    return remainder_preview_cache.get_parsed(token, key)


def store_remainder_parsed(token: str, key: tuple, parsed: Any, rows: int) -> None:
    remainder_preview_cache.put_parsed(token, key, parsed, rows)
