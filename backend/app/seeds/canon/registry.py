"""Реестр канона: сборка + валидация PlantConfig из RAW-данных (ADR-0004).

build_plant_config() — единственная точка конструирования.
Вызывается в lifespan FastAPI, в session-scoped fixture, в CI-скрипте.
"""

from __future__ import annotations

from app.seeds.canon.models import (
    ColorToken,
    ColorsCanon,
    DisplayCanon,
    HangerRoundingRule,
    LabelsCanon,
    PlantConfig,
    ProcessingFlags,
    ProductionCanon,
    QualityCanon,
    RoutingCanon,
)


def build_plant_config() -> PlantConfig:
    """Собирает и валидирует PlantConfig из RAW-данных завода.

    Импортирует dict-литералы из plant_policies (authoring format),
    конвертирует в typed-модели, запускает cross-ref проверки.
    Объект не может существовать в невалидном виде.

    Raises:
        pydantic.ValidationError: при нарушении формы данных.
        ValueError: при нарушении cross-ref правил.
    """
    # RAW-данные (dict-литералы, authoring format)
    from app.seeds.plant_policies import (
        COLOR_TOKENS,
        HANGER_ROUNDING_RULE,
        PAIRED_PROCESSING_VALUE,
        STANDART_PROCESSING_VALUE,
        VALIDATION_ERROR_MESSAGES,
    )

    # Конвертация в typed-модели
    color_tokens = [ColorToken.model_validate(d) for d in COLOR_TOKENS]
    hanger_rounding = HangerRoundingRule.model_validate(HANGER_ROUNDING_RULE)
    processing_flags = ProcessingFlags(
        paired=PAIRED_PROCESSING_VALUE,
        standart=STANDART_PROCESSING_VALUE,
    )

    # Cross-ref валидация (tracer bullet: правила 2, 3, 6)
    _validate_no_duplicate_color_tokens(color_tokens)
    _validate_required_fields_non_empty(color_tokens)
    _validate_enum_validity(hanger_rounding)

    return PlantConfig(
        production=ProductionCanon(
            hanger_rounding=hanger_rounding,
            processing_flags=processing_flags,
        ),
        routing=RoutingCanon(),
        quality=QualityCanon(),
        display=DisplayCanon(
            colors=ColorsCanon(tokens=color_tokens),
            labels=LabelsCanon(error_messages=dict(VALIDATION_ERROR_MESSAGES)),
        ),
    )


# ─── Cross-ref проверки ───────────────────────────────────────────────────────


def _validate_no_duplicate_color_tokens(tokens: list[ColorToken]) -> None:
    """Правило 2: нет дублей code в каждом наборе."""
    seen: set[str] = set()
    for t in tokens:
        if t.token in seen:
            raise ValueError(f"Duplicate color token: {t.token!r}")
        seen.add(t.token)


def _validate_required_fields_non_empty(tokens: list[ColorToken]) -> None:
    """Правило 3: обязательные поля не пустые."""
    for t in tokens:
        if not t.token.strip():
            raise ValueError("ColorToken.token must not be blank")
        if not t.color.strip():
            raise ValueError("ColorToken.color must not be blank")


def _validate_enum_validity(rule: HangerRoundingRule) -> None:
    """Правило 6: enum-поля содержат только допустимые значения."""
    # mode уже валидирован pydantic Literal; здесь — явная проверка для CI
    if rule.mode != "round_up_to_multiple":
        raise ValueError(f"Invalid hanger rounding mode: {rule.mode!r}")
