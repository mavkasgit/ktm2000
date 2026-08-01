"""Типизированные модели канона заводской конфигурации (ADR-0004).

PlantConfig — корневой объект; доменные суб-модели группируют данные
по ответственности. Валидация формы = часть конструирования (pydantic).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ─── Display canon ────────────────────────────────────────────────────────────


class ColorToken(BaseModel):
    """Токен извлечения цвета при импорте."""

    token: str = Field(min_length=1)
    color: str = Field(min_length=1)


class LabelsCanon(BaseModel):
    """Тексты ошибок валидации и прочие UI-лейблы."""

    error_messages: dict[str, str] = Field(default_factory=dict)

    @field_validator("error_messages")
    @classmethod
    def _keys_non_empty(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if not key.strip():
                raise ValueError("error_messages key must not be blank")
        return v


class ColorsCanon(BaseModel):
    """Канон цветовых токенов завода."""

    tokens: list[ColorToken] = Field(default_factory=list)

    @field_validator("tokens")
    @classmethod
    def _no_duplicate_tokens(cls, v: list[ColorToken]) -> list[ColorToken]:
        seen: set[str] = set()
        for item in v:
            if item.token in seen:
                raise ValueError(f"Duplicate color token: {item.token!r}")
            seen.add(item.token)
        return v


class RolesCanon(BaseModel):
    """Каталог ролей (заглушка для тикета #26)."""

    catalog: dict[str, str] = Field(default_factory=dict)


class DisplayCanon(BaseModel):
    """Всё, что связано с отображением: лейблы, цвета, роли."""

    colors: ColorsCanon = Field(default_factory=ColorsCanon)
    labels: LabelsCanon = Field(default_factory=LabelsCanon)
    roles: RolesCanon = Field(default_factory=RolesCanon)


# ─── Production canon ─────────────────────────────────────────────────────────


class HangerRoundingRule(BaseModel):
    """Правило округления количества до подвески."""

    enabled: bool = True
    mode: Literal["round_up_to_multiple"] = "round_up_to_multiple"


class ProcessingFlags(BaseModel):
    """Значения признаков обработки техкарт."""

    paired: str = Field(min_length=1)
    standart: str = Field(min_length=1)


class ProductionCanon(BaseModel):
    """Производственные политики: участки, операции, подвески, обработка."""

    hanger_rounding: HangerRoundingRule = Field(default_factory=HangerRoundingRule)
    processing_flags: ProcessingFlags
    # sections, ops, scrap_policy, stock_locations — заглушки для #23/#25
    sections: list[dict] = Field(default_factory=list)
    ops: list[dict] = Field(default_factory=list)


# ─── Routing canon (заглушка для #24) ────────────────────────────────────────


class RoutingCanon(BaseModel):
    """Правила выбора маршрутов, профили, SPG."""

    selection_rules: list[dict] = Field(default_factory=list)
    route_rule_profiles: list[dict] = Field(default_factory=list)
    spgs: list[dict] = Field(default_factory=list)


# ─── Quality canon (заглушка для #25) ────────────────────────────────────────


class QualityCanon(BaseModel):
    """Карта брака и решения по дефектам."""

    defect_decision_map: dict[str, str] = Field(default_factory=dict)


# ─── Root ─────────────────────────────────────────────────────────────────────


class PlantConfig(BaseModel):
    """Корневой типизированный объект заводской конфигурации.

    Не может существовать в невалидном виде — pydantic гарантирует
    форму при конструировании, cross-ref проверки в registry.
    """

    production: ProductionCanon
    routing: RoutingCanon = Field(default_factory=RoutingCanon)
    quality: QualityCanon = Field(default_factory=QualityCanon)
    display: DisplayCanon = Field(default_factory=DisplayCanon)
