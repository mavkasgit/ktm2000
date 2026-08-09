"""Чистый движок авторасчёта «количество на подвес» (спек #59, тикет #62).

Методика заказчика (Excel, строка ЮП-460):

    by_area = floor(area_limit_m2 / (perimeter_mm * length_mm / 10**6))
    by_size = floor(rod_length_mm / (mount_width_mm + gap_mm)) * rod_count
    total   = min(by_area, by_size)

Модуль чистый: без БД, без асинхронности. Константы подвеса всегда
передаются параметром ``hanger: HangerSettings`` (дефолты 13/1450/20/2
зашиты в коде). Смежный :mod:`app.services.hanger_quantity` (округление
количества до кратного) не трогаем.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, TypeGuard


class HangerConfigError(ValueError):
    """Некорректные константы подвеса или несовместимые габариты на входе."""


@dataclass(frozen=True)
class HangerSettings:
    """Настройки подвеса. Дефолты — значения заказчика (13 / 1450 / 20 / 2)."""

    area_limit_m2: float = 13.0
    rod_length_mm: float = 1450.0
    gap_mm: float = 20.0
    rod_count: int = 2

    def validate(self) -> None:
        """Валидация констант на входе. Бросает HangerConfigError."""
        if not math.isfinite(self.area_limit_m2) or self.area_limit_m2 <= 0:
            raise HangerConfigError("area_limit_m2 должен быть конечным числом > 0")
        if not math.isfinite(self.rod_length_mm) or self.rod_length_mm <= 0:
            raise HangerConfigError("rod_length_mm должен быть конечным числом > 0")
        if not math.isfinite(self.gap_mm) or self.gap_mm < 0:
            raise HangerConfigError("gap_mm должен быть конечным числом >= 0")
        if self.rod_count < 1:
            raise HangerConfigError("rod_count должен быть >= 1")


DEFAULT_HANGER_SETTINGS = HangerSettings()


def _is_valid(value: float | None) -> TypeGuard[float]:
    """Расчётное значение: не None, конечное число > 0 (TypeGuard сужает тип)."""
    return value is not None and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class HangerCalcResult:
    """Разбивка расчёта количества на подвес.

    При нерасчётных данных (нет длины / нет авто-полей) ``is_calculable=False``,
    остальные поля ``None``. Исключения при этом не бросаются.
    """

    by_area: int | None
    by_size: int | None
    total: int | None
    limiter: Literal["area", "size"] | None
    area_m2: float | None
    is_calculable: bool


def _non_calculable() -> HangerCalcResult:
    """Результат нерасчётных данных: is_calculable=False, поля None."""
    return HangerCalcResult(
        by_area=None,
        by_size=None,
        total=None,
        limiter=None,
        area_m2=None,
        is_calculable=False,
    )


def _finalize(area_m2: float, by_area: int, by_size: int) -> HangerCalcResult:
    """Общий хвост расчёта: лимитер (по площади, если не больше по размеру) и итог = min."""
    limiter: Literal["area", "size"] = "area" if by_area <= by_size else "size"
    return HangerCalcResult(
        by_area=by_area,
        by_size=by_size,
        total=min(by_area, by_size),
        limiter=limiter,
        area_m2=area_m2,
        is_calculable=True,
    )


def compute_hanger_quantity(
    *,
    perimeter_mm: float | None,
    mount_width_mm: float | None,
    length_mm: float | None,
    hanger: HangerSettings | None = None,
) -> HangerCalcResult:
    """Посчитать количество на подвес по периметру, габариту и длине.

    Args:
        perimeter_mm: Периметр сечения профиля, мм (>0 для расчёта).
        mount_width_mm: Габарит профиля, мм (>0 для расчёта).
        length_mm: Длина профиля, мм (>0 для расчёта).
        hanger: Настройки подвеса; по умолчанию 13/1450/20/2.

    Returns:
        HangerCalcResult. ``is_calculable=False`` и поля ``None`` — если
        отсутствует длина или хотя бы одно авто-поле (периметр/габарит).

    Raises:
        HangerConfigError: некорректные константы или кросс-поле
            ``mount_width_mm + gap_mm > rod_length_mm`` (не влезает на клюшку).
    """
    settings = hanger or DEFAULT_HANGER_SETTINGS
    settings.validate()

    if (
        not _is_valid(perimeter_mm)
        or not _is_valid(mount_width_mm)
        or not _is_valid(length_mm)
    ):
        return _non_calculable()

    if mount_width_mm + settings.gap_mm > settings.rod_length_mm:
        raise HangerConfigError(
            "Несовместимые данные: габарит + зазор превышают рабочую длину клюшки "
            f"({mount_width_mm} + {settings.gap_mm} > {settings.rod_length_mm})"
        )

    area_m2 = perimeter_mm * length_mm / 1_000_000
    by_area = math.floor(settings.area_limit_m2 / area_m2)
    by_size = math.floor(settings.rod_length_mm / (mount_width_mm + settings.gap_mm)) * settings.rod_count

    return _finalize(area_m2, by_area, by_size)


def compute_paired_hanger_quantity(
    *,
    perimeter_a_mm: float | None,
    mount_width_a_mm: float | None,
    perimeter_b_mm: float | None,
    mount_width_b_mm: float | None,
    length_mm: float | None,
    hanger: HangerSettings | None = None,
) -> HangerCalcResult:
    """Совместный расчёт количества на подвес для парной техкарты (#58/#67).

    Пара висит на подвесе как единая загрузка ``N×A + N×B``, поэтому считаем
    по сумме периметров и габаритов:

        by_area = floor(area_limit_m2 / ((perimeter_A + perimeter_B) * length / 10**6))
        by_size = floor(rod_length_mm * rod_count / ((width_A + width_B) + gap_mm * 2))
        total   = min(by_area, by_size)

    Константы — те же ``HangerSettings``, что и для одиночного расчёта
    (единые константы, дефолты 13/1450/20/2): ``by_size`` при дефолтах
    эквивалентен ``floor(2900 / (width_A + width_B + 40))``.

    Args:
        perimeter_a_mm / perimeter_b_mm: Периметры профилей A и B, мм.
        mount_width_a_mm / mount_width_b_mm: Габариты профилей A и B, мм.
        length_mm: Общая длина пары, мм.
        hanger: Настройки подвеса; по умолчанию 13/1450/20/2.

    Returns:
        HangerCalcResult. ``is_calculable=False`` и поля ``None`` — если нет
        общей длины или у одного из артикулов нет авто-поля (периметр/габарит).
        Авто-режим пары возможен только когда оба артикула авто.

    Raises:
        HangerConfigError: некорректные константы или кросс-поле
            ``width_A + width_B + gap*2 > rod_length * rod_count`` (пара не
            влезает на подвес суммарно — ``by_size`` обратился бы в 0).
    """
    settings = hanger or DEFAULT_HANGER_SETTINGS
    settings.validate()

    if (
        not _is_valid(perimeter_a_mm)
        or not _is_valid(mount_width_a_mm)
        or not _is_valid(perimeter_b_mm)
        or not _is_valid(mount_width_b_mm)
        or not _is_valid(length_mm)
    ):
        return _non_calculable()

    if (
        mount_width_a_mm + mount_width_b_mm + settings.gap_mm * 2
        > settings.rod_length_mm * settings.rod_count
    ):
        raise HangerConfigError(
            "Несовместимые данные: сумма габаритов пары + зазоры превышает "
            "рабочую длину клюшек "
            f"({mount_width_a_mm} + {mount_width_b_mm} + {settings.gap_mm * 2} "
            f"> {settings.rod_length_mm * settings.rod_count})"
        )

    combined_perimeter = perimeter_a_mm + perimeter_b_mm
    combined_width = mount_width_a_mm + mount_width_b_mm
    area_m2 = combined_perimeter * length_mm / 1_000_000
    by_area = math.floor(settings.area_limit_m2 / area_m2)
    by_size = math.floor(
        settings.rod_length_mm * settings.rod_count
        / (combined_width + settings.gap_mm * 2)
    )

    return _finalize(area_m2, by_area, by_size)
