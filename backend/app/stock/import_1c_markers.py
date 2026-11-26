"""Маркеры выполненных операций в наименовании строки ОСВ 1С (#468).

В выгрузке 1С нет колонки «выполненные операции»: цвет, пресс и
полуфабрикат закодированы в наименовании. Модуль только читает эти
маркеры — маршрут и префикс операций собирает вызывающий
(``import_1c_osv.resolve_1c_osv_completed_operations``).

Правила — данные, а не код: ключевые слова цвета приходят из правила
``anod_colors``, пресса — из ``press_types``, имена операций — из
``section_operations``. Поэтому здесь нет ни списка цветов, ни списка
прессов.

Границы разбора (тикет #468):

* суффикс ``-NN`` считается цветом только сразу после артикула строки
  (SKU или его алиаса) либо отдельной группой ``– 02`` — иначе
  ``РП-АКП-08`` и ``404.00.00.002-01`` стали бы цветом чужого профиля;
* слово и суффикс обязаны совпадать: ``-05`` и «золото» — конфликт;
* ``ПФ``/``П/ф`` — полуфабрикат, иначе ГП;
* «не угадывать»: неоднозначность и расхождение — ошибка строки.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.services.import_normalization import normalize_sku, sku_loose

#: ``ПФ``, ``П/ф``, ``П \\ ф`` — полуфабрикат. Границы слова не дают поймать
#: «ПФ» внутри другого слова.
_PF_RE = re.compile(r"(?<![а-яёa-z])п\s*[/\\]?\s*ф(?![а-яёa-z])", re.IGNORECASE)

#: Отдельная группа «– 02»: тире, пробелы и ровно две цифры. Дефис внутри
#: кода (``404.00.00.002-01``, ``РП-АКП-08``) не подходит — перед ним буква
#: или цифра. Запятая после номера — диапазон исполнений (``-01,02``).
_STANDALONE_SUFFIX_RE = re.compile(r"(?<![\w-])[-–—]\s*(\d{2})(?![\d,])")


@dataclass(frozen=True)
class ColorVocabulary:
    """Словарь маркеров, прочитанный из справочника.

    ``color_keywords`` и ``press_keywords`` — пары (ключевое слово, код
    операции) в порядке правила: при равной длине совпадения побеждает
    первое, поэтому «старое золото» стоит раньше «золот».
    """

    color_keywords: tuple[tuple[str, str], ...] = ()
    color_names: Mapping[str, str] = field(default_factory=dict)
    press_keywords: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class OsvMarkers:
    """Разобранные маркеры строки ОСВ."""

    color_code: str | None = None
    color_name: str | None = None
    press_code: str | None = None
    press_keyword: str | None = None
    is_semi_finished: bool = False
    errors: tuple[str, ...] = ()

    @property
    def has_markers(self) -> bool:
        return bool(self.color_code or self.press_code or self.is_semi_finished)


def _color_word_hit(
    text: str, vocabulary: ColorVocabulary
) -> tuple[str, str] | None:
    """Самое длинное совпадение по ``anod_colors``: ``(код, слово)``.

    Равная длина у разных кодов — неоднозначность, а не выбор первого:
    возвращаем ``None`` и ошибку через :func:`_color_word_error`.
    """
    hits = [
        (keyword, code)
        for keyword, code in vocabulary.color_keywords
        if keyword and keyword in text
    ]
    if not hits:
        return None
    longest = max(len(keyword) for keyword, _ in hits)
    best = [(keyword, code) for keyword, code in hits if len(keyword) == longest]
    codes = {code for _, code in best}
    if len(codes) > 1:
        return None
    return best[0][1], best[0][0]


def _color_word_is_ambiguous(text: str, vocabulary: ColorVocabulary) -> bool:
    hits = [
        (keyword, code)
        for keyword, code in vocabulary.color_keywords
        if keyword and keyword in text
    ]
    if not hits:
        return False
    longest = max(len(keyword) for keyword, _ in hits)
    return len({code for keyword, code in hits if len(keyword) == longest}) > 1


def _suffix_codes(
    text: str, anchors: set[str], vocabulary: ColorVocabulary
) -> set[str]:
    """Коды цветов из суффиксов ``-NN`` (только существующие ANOD_xx)."""
    valid = set(vocabulary.color_names)
    codes: set[str] = set()

    for anchor in anchors:
        variants = {normalize_sku(anchor), sku_loose(anchor)} - {""}
        for variant in variants:
            pattern = re.compile(
                rf"(?<![\w-]){re.escape(variant)}-(\d{{2}})(?![\d,])"
            )
            for match in pattern.finditer(text):
                code = f"ANOD_{match.group(1)}"
                if code in valid:
                    codes.add(code)

    for match in _STANDALONE_SUFFIX_RE.finditer(text):
        code = f"ANOD_{match.group(1)}"
        if code in valid:
            codes.add(code)

    return codes


def extract_osv_markers(
    name: str | None,
    *,
    anchors: set[str],
    vocabulary: ColorVocabulary,
) -> OsvMarkers:
    """Разобрать цвет, пресс и признак полуфабриката из наименования ОСВ.

    ``anchors`` — SKU и алиасы найденного артикула: только их суффикс
    ``-NN`` считается цветом. Пустой набор — цвет ищется лишь отдельной
    группой «– 02» и словом.
    """
    text = (name or "").lower()
    errors: list[str] = []

    suffix_codes = _suffix_codes(text, anchors, vocabulary)
    suffix_code: str | None = None
    suffix_nn: str | None = None
    if len(suffix_codes) > 1:
        names = ", ".join(
            f"{code} ({vocabulary.color_names.get(code, code)})"
            for code in sorted(suffix_codes)
        )
        errors.append(f"Цвет неоднозначен: суффиксы дают {names}")
    elif suffix_codes:
        suffix_code = next(iter(suffix_codes))
        suffix_nn = suffix_code.removeprefix("ANOD_")

    if _color_word_is_ambiguous(text, vocabulary):
        errors.append("Цвет неоднозначен: в наименовании несколько цветов")
    word_hit = _color_word_hit(text, vocabulary)

    if word_hit is not None and suffix_code is not None:
        word_code, word_keyword = word_hit
        if word_code != suffix_code:
            errors.append(
                "Цвет не совпадает: суффикс "
                f"«-{suffix_nn}» ({vocabulary.color_names.get(suffix_code, suffix_code)}) "
                f"и слово «{word_keyword}» "
                f"({vocabulary.color_names.get(word_code, word_code)})"
            )

    color_code = None
    if not errors:
        color_code = suffix_code or (word_hit[0] if word_hit is not None else None)

    press_codes = {
        code for keyword, code in vocabulary.press_keywords if keyword and keyword in text
    }
    press_code: str | None = None
    press_keyword: str | None = None
    if len(press_codes) > 1:
        errors.append("Пресс неоднозначен: в наименовании и «окно», и «гребенка»")
    elif press_codes:
        press_code = next(iter(press_codes))
        press_keyword = next(
            keyword
            for keyword, code in vocabulary.press_keywords
            if code == press_code and keyword in text
        )

    return OsvMarkers(
        color_code=color_code if not errors else None,
        color_name=(
            vocabulary.color_names.get(color_code)
            if color_code is not None and not errors
            else None
        ),
        press_code=press_code if not errors else None,
        press_keyword=press_keyword if not errors else None,
        is_semi_finished=bool(_PF_RE.search(text)),
        errors=tuple(errors),
    )
