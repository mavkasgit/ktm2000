"""Stateless batch-эндпоинт авторасчёта «количество на подвес» (#62).

Контракт: вход {items, hanger}, выход {results, hanger} в порядке items.
Single = batch из одного item. Вход — числа, не id. Нерасчётные данные →
``is_calculable=false`` без исключений. Невалидные константы/кросс-поле → 422.
Константы (read-only) отдаются в ответе, чтобы фронт не дублировал их в TS.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.hanger_quantity_calc import (
    DEFAULT_HANGER_SETTINGS,
    HangerConfigError,
    HangerSettings,
    compute_hanger_quantity,
    compute_paired_hanger_quantity,
)

router = APIRouter(prefix="/hanger-calc", tags=["hanger-calc"])


class HangerSettingsIn(BaseModel):
    # Валидация констант — в HangerSettings.validate() (движок — единственный
    # авторитет); Pydantic не дублирует границы, чтобы NaN/Infinity доходили до
    # движка и давали чистый 422 вместо обрыва сериализации ошибки фреймворком.
    area_limit_m2: float = Field(
        default=DEFAULT_HANGER_SETTINGS.area_limit_m2,
        description="Лимит площади на подвес, м²",
    )
    rod_length_mm: float = Field(
        default=DEFAULT_HANGER_SETTINGS.rod_length_mm,
        description="Рабочая длина клюшки, мм",
    )
    gap_mm: float = Field(
        default=DEFAULT_HANGER_SETTINGS.gap_mm,
        description="Зазор между профилями, мм",
    )
    rod_count: int = Field(
        default=DEFAULT_HANGER_SETTINGS.rod_count,
        description="Количество клюшек на подвесе",
    )


class HangerCalcItemIn(BaseModel):
    perimeter_mm: float | None = None
    mount_width_mm: float | None = None
    length_mm: float | None = None


class PairedHangerCalcItemIn(BaseModel):
    perimeter_a_mm: float | None = None
    mount_width_a_mm: float | None = None
    perimeter_b_mm: float | None = None
    mount_width_b_mm: float | None = None
    length_mm: float | None = None


class HangerCalcRequest(BaseModel):
    items: list[HangerCalcItemIn]
    hanger: HangerSettingsIn = Field(default_factory=HangerSettingsIn)


class PairedHangerCalcRequest(BaseModel):
    items: list[PairedHangerCalcItemIn]
    hanger: HangerSettingsIn = Field(default_factory=HangerSettingsIn)


class HangerCalcResultOut(BaseModel):
    by_area: int | None
    by_size: int | None
    total: int | None
    limiter: Literal["area", "size"] | None
    area_m2: float | None
    is_calculable: bool


class HangerCalcResponse(BaseModel):
    results: list[HangerCalcResultOut]
    hanger: HangerSettingsIn


@router.post("", response_model=HangerCalcResponse)
async def hanger_calc(payload: HangerCalcRequest) -> HangerCalcResponse:
    settings = HangerSettings(**payload.hanger.model_dump())
    try:
        settings.validate()
    except HangerConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results: list[HangerCalcResultOut] = []
    for item in payload.items:
        try:
            result = compute_hanger_quantity(
                perimeter_mm=item.perimeter_mm,
                mount_width_mm=item.mount_width_mm,
                length_mm=item.length_mm,
                hanger=settings,
            )
        except HangerConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        results.append(HangerCalcResultOut(**asdict(result)))

    return HangerCalcResponse(results=results, hanger=payload.hanger)


@router.post("/paired", response_model=HangerCalcResponse)
async def hanger_calc_paired(payload: PairedHangerCalcRequest) -> HangerCalcResponse:
    """Совместный batch-расчёт для парных техкарт (#58/#67).

    Вход — числа, не id: {items: [{perimeter_a_mm, mount_width_a_mm,
    perimeter_b_mm, mount_width_b_mm, length_mm}], hanger}. Выход {results,
    hanger} в порядке items. Авто возможен только когда оба артикула авто;
    иначе — ``is_calculable=false`` без исключений. Невалидные константы и
    кросс-поле (сумма габаритов пары не влезает на подвес) → 422.
    """
    settings = HangerSettings(**payload.hanger.model_dump())
    try:
        settings.validate()
    except HangerConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results: list[HangerCalcResultOut] = []
    for item in payload.items:
        try:
            result = compute_paired_hanger_quantity(
                perimeter_a_mm=item.perimeter_a_mm,
                mount_width_a_mm=item.mount_width_a_mm,
                perimeter_b_mm=item.perimeter_b_mm,
                mount_width_b_mm=item.mount_width_b_mm,
                length_mm=item.length_mm,
                hanger=settings,
            )
        except HangerConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        results.append(HangerCalcResultOut(**asdict(result)))

    return HangerCalcResponse(results=results, hanger=payload.hanger)
