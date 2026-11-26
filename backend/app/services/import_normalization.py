from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func

DEFAULT_IMPORT_NORMALIZATION_RULES: dict[str, Any] = {}

#: Варианты написания тире (unicode-дефисы, минус, широкий дефис и т.п.),
#: которые при нормализации артикула сводятся к обычному ``-``. Открыто:
#: предфильтр импорта остатков воспроизводит то же правило в SQL (#347).
SKU_DASH_VARIANTS = "\u2010\u2011\u2012\u2013\u2014\u2212\u2043\uFE58\uFE63\uFF0D"


def normalize_sku(value: str) -> str:
    """Нормализация артикула для сравнения/поиска.

    Приводит к нижнему регистру, срезает пробелы, унифицирует все варианты
    тире в обычный ``-`` и убирает все пробелы (включая неразрывный).
    """
    normalized = (value or "").strip().lower()
    for ch in SKU_DASH_VARIANTS:
        normalized = normalized.replace(ch, "-")
    return normalized.replace(" ", "").replace("\u00A0", "")


_DASH_BETWEEN_LETTER_AND_DIGIT = re.compile(r"(?<=[a-zа-яё])-(?=\d)")


def sku_loose(value: str) -> str:
    """Артикул без дефиса между буквой и цифрой: ``ALS-1291`` == ``ALS1291``.

    Дефис здесь — оформление, а не часть кода: 1С пишет ``ALS1291``, справочник —
    ``ALS-1291``. Хвост (``sku_tail``) и числовой ключ по-прежнему считаются по
    исходному SKU: это отдельные правила, не нормализация.
    """
    return _DASH_BETWEEN_LETTER_AND_DIGIT.sub("", normalize_sku(value))


_SQL_LOOSE_PATTERN = r"([a-zа-яё])-([0-9])"


def sku_loose_sql(column):
    """SQL-аналог ``sku_loose`` для колонки SKU (PostgreSQL).

    Предфильтр остатков и точный ``IN``-фолбэк пар выбирают кандидатов в SQL, а
    окончательное решение принимает Python. Без SQL-копии правила кандидат с
    другим написанием просто не доезжает — и ``sku_loose`` не срабатывает уже
    никогда. Выражение повторяет ``normalize_sku`` (регистр, варианты тире,
    пробелы) и снимает дефис только между буквой и цифрой — тем же шаблоном,
    что и Python, без lookbehind (его нет в старых версиях PostgreSQL).
    """
    dashed = func.translate(
        func.lower(column), SKU_DASH_VARIANTS, "-" * len(SKU_DASH_VARIANTS)
    )
    no_spaces = func.replace(func.replace(dashed, " ", ""), "\u00A0", "")
    return func.regexp_replace(no_spaces, _SQL_LOOSE_PATTERN, r"\1\2", "g")


def numeric_sku_key(value: str) -> str | None:
    """Числовой ключ чисто цифрового артикула без ведущих нулей (#444).

    ``033`` → ``33``, ``0033`` → ``33``, ``000`` → ``0``. У артикула с
    буквами, дефисом или слэшем ключа нет: ``ЮП-033`` и ``033`` остаются
    разными артикулами.

    Отдельный ключ, а не правило внутри ``normalize_sku``: нормализованное
    написание используется и для точных сравнений (остатки, ключи словаря),
    где склейка ``033`` с ``33`` была бы подменой артикула.
    """
    normalized = normalize_sku(value)
    if not normalized.isascii() or not normalized.isdigit():
        return None
    return normalized.lstrip("0") or "0"


_SKU_COMPOUND_SEPARATOR = "/"


def sku_compound_parts(value: str | None) -> list[str]:
    """Нормализованные части составного артикула по ``/``, в порядке ячейки.

    Меньше двух непустых частей — артикул не составной: у ``ЮП-3658/`` иначе
    появлялась бы одна «часть», и строка получила бы ложное предупреждение.
    """
    if not value or _SKU_COMPOUND_SEPARATOR not in value:
        return []
    parts: list[str] = []
    for chunk in value.split(_SKU_COMPOUND_SEPARATOR):
        part = normalize_sku(chunk)
        if part and part not in parts:
            parts.append(part)
    return parts if len(parts) > 1 else []


def sku_tail(sku: str) -> str:
    """Хвост артикула после последнего тире: ``ЮП-1875`` → ``1875``.

    У SKU без тире хвостом считается весь артикул: сравнение части с ним и так
    покрыто точным совпадением, отдельного правила не нужно.
    """
    normalized = normalize_sku(sku)
    _, separator, tail = normalized.rpartition("-")
    return tail if separator and tail else normalized


@dataclass(frozen=True, slots=True)
class SkuEntry:
    """Один артикул справочника в каскаде привязки.

    ``keys`` — написания, по которым артикул узнаётся как точный SKU (у импорта
    плана их несколько: регистр, нормализация, mojibake-восстановление),
    ``tail`` — хвост после последнего тире, ``numeric_key`` — числовой ключ
    чисто цифрового SKU (#444). Запись одна на артикул, поэтому несколько
    ключей одного продукта не могут родить ложную неоднозначность.

    ``loose_keys`` — те же написания без дефиса между буквой и цифрой:
    ``ALS-1291`` узнаётся и как ``ALS1291`` (1С пишет код поставщика без
    дефиса). Это шаг каскада, а не ещё один SKU: группы алиасов и хвост
    по-прежнему считаются по исходному написанию.

    Числовой ключ лежит отдельно от ``keys`` намеренно: в точном цикле
    ``match_sku_cell`` первый ключ победил бы молча, а записи ``33`` и ``033``
    обязаны дать неоднозначность, а не выбор по порядку справочника.
    """

    keys: frozenset[str]
    tail: str
    numeric_key: str | None = None
    loose_keys: frozenset[str] = frozenset()


def sku_entry(sku: str, extra_keys: Iterable[str] = ()) -> SkuEntry:
    """Запись справочника: нормализованный SKU, его хвост и допустимые написания.

    ``extra_keys`` — альтернативные написания того же артикула (mojibake-
    восстановление импорта плана). Нормализованный SKU входит в ключи всегда: на
    него опирается точное совпадение целой ячейки. Числовой ключ считается
    только по SKU продукта: алиас чужого артикула не должен превращать
    ``ЮП-033`` в числовой ``33``.
    """
    normalized = normalize_sku(sku)
    keys = frozenset({normalized, *extra_keys} - {""})
    return SkuEntry(
        keys=keys,
        tail=sku_tail(sku),
        numeric_key=numeric_sku_key(sku),
        loose_keys=frozenset(sku_loose(key) for key in keys if key),
    )


@dataclass(frozen=True, slots=True)
class SkuMatch:
    """Исход сопоставления ячейки списку артикулов.

    ``index`` — позиция найденной записи в переданном списке (``None``, если
    привязки нет), ``part`` — часть, по которой нашли (``None`` у точного
    совпадения целой ячейки), ``numeric_key`` — числовой ключ, по которому
    нашли (``None`` у остальных шагов), ``ambiguous_indexes`` — позиции
    записей, к которым подходит одна часть или один числовой ключ: привязки
    нет и быть не должно.
    """

    index: int | None = None
    part: str | None = None
    numeric_key: str | None = None
    ambiguous_indexes: tuple[int, ...] = ()

    @property
    def found(self) -> bool:
        return self.index is not None

    @property
    def rejected(self) -> bool:
        return bool(self.ambiguous_indexes)


def match_sku_numeric(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Числовой ключ чисто цифрового артикула против справочника (#444).

    ``33`` и ``033`` — один артикул, пока такой числовой ключ в справочнике
    один. Несколько записей с тем же ключом (``33`` и ``033``) — неоднозначность:
    привязки нет, выбор по порядку справочника был бы подменой артикула.
    """
    key = numeric_sku_key(cell)
    if key is None:
        return SkuMatch()
    hits = tuple(
        index for index, entry in enumerate(entries) if entry.numeric_key == key
    )
    if len(hits) == 1:
        return SkuMatch(index=hits[0], numeric_key=key)
    if len(hits) > 1:
        return SkuMatch(numeric_key=key, ambiguous_indexes=hits)
    return SkuMatch()


def match_sku_parts(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Части составного артикула по «/» против справочника (#347, ADR-0067).

    Часть ищется как точный SKU артикула и как его хвост после тире, поэтому
    голый сегмент «1875» находит «ЮП-1875». Вторая часть рассматривается только
    когда первая ни к чему не привязалась. Неоднозначность останавливает поиск,
    а не переходит к следующей части: иначе строка уехала бы на молча выбранном
    артикуле, и оператор этого не заметил бы.
    """
    for part in sku_compound_parts(cell):
        loose_part = sku_loose(part)
        hits = tuple(
            index
            for index, entry in enumerate(entries)
            if part in entry.keys
            or part == entry.tail
            or loose_part in entry.loose_keys
        )
        if len(hits) == 1:
            return SkuMatch(index=hits[0], part=part)
        if len(hits) > 1:
            return SkuMatch(part=part, ambiguous_indexes=hits)
    return SkuMatch()


def match_sku_loose(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Совпадение без дефиса между буквой и цифрой: ``ALS1291`` ↔ ``ALS-1291``.

    Отдельный шаг каскада, а не правило внутри точного совпадения: импорт плана
    задаёт свой первый шаг (восстановление кодировки) и вызывает этот же шаг
    между числовым кодом и частями. Правило одно — ``sku_loose``.
    """
    loose = sku_loose(cell)
    if not loose:
        return SkuMatch()
    hits = tuple(
        index for index, entry in enumerate(entries) if loose in entry.loose_keys
    )
    if len(hits) == 1:
        return SkuMatch(index=hits[0])
    if len(hits) > 1:
        return SkuMatch(ambiguous_indexes=hits)
    return SkuMatch()


def match_sku_cell(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Каскад привязки: целая ячейка → числовой код → без дефиса → части (#347, #444).

    Точное совпадение обязано идти первым: артикул со слэшем в справочнике легален
    (``Product.sku`` уникален целиком), и привязывать его к первой части было бы
    ошибкой. Числовой код (``33`` ↔ ``033``) — следующий шаг: он сравнивает SKU
    по значению, но только когда такой код в справочнике один. Импорт плана
    задаёт точное совпадение шире (восстановление кодировки легаси-файлов),
    поэтому у него свой первый шаг, а числовой шаг и ``match_sku_parts`` общие.
    """
    normalized_cell = normalize_sku(cell)
    for index, entry in enumerate(entries):
        if normalized_cell in entry.keys:
            return SkuMatch(index=index)
    numeric_match = match_sku_numeric(normalized_cell, entries)
    if numeric_match.found or numeric_match.rejected:
        return numeric_match
    loose_match = match_sku_loose(normalized_cell, entries)
    if loose_match.found or loose_match.rejected:
        return loose_match
    return match_sku_parts(normalized_cell, entries)


def default_import_normalization_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_IMPORT_NORMALIZATION_RULES)


def has_valid_normalization_rules(value: Any) -> bool:
    """Normalization rules are deprecated — always return False."""
    return False


def apply_import_normalization(
    *,
    raw_operation: str | None,
    raw_output_kind: str | None,
    normalization_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    """No-op — normalization is handled by route selection rules now."""
    return {
        "operation_code": None,
        "operation_name": None,
        "additional_pack_operations": [],
        "normalized_pack_op_family": "NONE",
        "output_kind": raw_output_kind,
    }


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
