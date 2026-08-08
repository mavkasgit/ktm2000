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
from typing import Literal


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
        perimeter_mm is None
        or not math.isfinite(perimeter_mm)
        or perimeter_mm <= 0
        or mount_width_mm is None
        or not math.isfinite(mount_width_mm)
        or mount_width_mm <= 0
        or length_mm is None
        or not math.isfinite(length_mm)
        or length_mm <= 0
    ):
        return HangerCalcResult(
            by_area=None,
            by_size=None,
            total=None,
            limiter=None,
            area_m2=None,
            is_calculable=False,
        )

    if mount_width_mm + settings.gap_mm > settings.rod_length_mm:
        raise HangerConfigError(
            "Несовместимые данные: габарит + зазор превышают рабочую длину клюшки "
            f"({mount_width_mm} + {settings.gap_mm} > {settings.rod_length_mm})"
        )

    area_m2 = perimeter_mm * length_mm / 1_000_000
    by_area = math.floor(settings.area_limit_m2 / area_m2)
    by_size = math.floor(settings.rod_length_mm / (mount_width_mm + settings.gap_mm)) * settings.rod_count

    if by_area <= by_size:
        limiter: Literal["area", "size"] = "area"
    else:
        limiter = "size"

    return HangerCalcResult(
        by_area=by_area,
        by_size=by_size,
        total=min(by_area, by_size),
        limiter=limiter,
        area_m2=area_m2,
        is_calculable=True,
    )
