from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

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
    ``tail`` — хвост после последнего тире. Запись одна на артикул, поэтому
    несколько ключей одного продукта не могут родить ложную неоднозначность.
    """

    keys: frozenset[str]
    tail: str


def sku_entry(sku: str, extra_keys: Iterable[str] = ()) -> SkuEntry:
    """Запись справочника: нормализованный SKU, его хвост и допустимые написания.

    ``extra_keys`` — альтернативные написания того же артикула (mojibake-
    восстановление импорта плана). Нормализованный SKU входит в ключи всегда: на
    него опирается точное совпадение целой ячейки.
    """
    normalized = normalize_sku(sku)
    return SkuEntry(
        keys=frozenset({normalized, *extra_keys} - {""}),
        tail=sku_tail(sku),
    )


@dataclass(frozen=True, slots=True)
class SkuMatch:
    """Исход сопоставления ячейки списку артикулов.

    ``index`` — позиция найденной записи в переданном списке (``None``, если
    привязки нет), ``part`` — часть, по которой нашли (``None`` у точного
    совпадения целой ячейки), ``ambiguous_indexes`` — позиции записей, к которым
    подходит одна часть: привязки нет и быть не должно.
    """

    index: int | None = None
    part: str | None = None
    ambiguous_indexes: tuple[int, ...] = ()

    @property
    def found(self) -> bool:
        return self.index is not None

    @property
    def rejected(self) -> bool:
        return bool(self.ambiguous_indexes)


def match_sku_parts(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Части составного артикула по «/» против справочника (#347, ADR-0067).

    Часть ищется как точный SKU артикула и как его хвост после тире, поэтому
    голый сегмент «1875» находит «ЮП-1875». Вторая часть рассматривается только
    когда первая ни к чему не привязалась. Неоднозначность останавливает поиск,
    а не переходит к следующей части: иначе строка уехала бы на молча выбранном
    артикуле, и оператор этого не заметил бы.
    """
    for part in sku_compound_parts(cell):
        hits = tuple(
            index
            for index, entry in enumerate(entries)
            if part in entry.keys or part == entry.tail
        )
        if len(hits) == 1:
            return SkuMatch(index=hits[0], part=part)
        if len(hits) > 1:
            return SkuMatch(part=part, ambiguous_indexes=hits)
    return SkuMatch()


def match_sku_cell(cell: str, entries: Sequence[SkuEntry]) -> SkuMatch:
    """Каскад привязки: целая ячейка → части по «/» (#347, ADR-0067).

    Точное совпадение обязано идти первым: артикул со слэшем в справочнике легален
    (``Product.sku`` уникален целиком), и привязывать его к первой части было бы
    ошибкой. Импорт плана задаёт точное совпадение шире (восстановление
    кодировки легаси-файлов), поэтому у него свой первый шаг, а ``match_sku_parts``
    общий у обоих.
    """
    normalized_cell = normalize_sku(cell)
    for index, entry in enumerate(entries):
        if normalized_cell in entry.keys:
            return SkuMatch(index=index)
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
