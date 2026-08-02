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
    OperationDef,
    PlantConfig,
    ProcessingFlags,
    ProductionCanon,
    QualityCanon,
    RoutingCanon,
    SectionDef,
    TransformingOpRef,
)


def build_plant_config() -> PlantConfig:
    """Собирает и валидирует PlantConfig из RAW-данных завода.

    Импортирует dict-литералы из plant_policies и sections_seeder
    (authoring format), конвертирует в typed-модели, запускает
    cross-ref проверки. Объект не может существовать в невалидном виде.

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
    from app.seeds.seeders.sections_seeder import (
        SECTIONS_DATA,
        SECTION_OPS,
        TRANSFORMING_SECTION_OPS,
    )

    # Конвертация в typed-модели
    color_tokens = [ColorToken.model_validate(d) for d in COLOR_TOKENS]
    hanger_rounding = HangerRoundingRule.model_validate(HANGER_ROUNDING_RULE)
    processing_flags = ProcessingFlags(
        paired=PAIRED_PROCESSING_VALUE,
        standart=STANDART_PROCESSING_VALUE,
    )
    sections = [SectionDef.model_validate(d) for d in SECTIONS_DATA]
    ops = _convert_section_ops(SECTION_OPS)
    transforming_ops = [
        TransformingOpRef(section_code=sc, operation_code=oc)
        for sc, oc in TRANSFORMING_SECTION_OPS
    ]

    # Cross-ref валидация
    _validate_no_duplicate_color_tokens(color_tokens)
    _validate_required_fields_non_empty(color_tokens)
    _validate_enum_validity(hanger_rounding)
    _validate_sections_cross_ref(sections, ops, transforming_ops)

    return PlantConfig(
        production=ProductionCanon(
            hanger_rounding=hanger_rounding,
            processing_flags=processing_flags,
            sections=sections,
            ops=ops,
            transforming_ops=transforming_ops,
        ),
        routing=RoutingCanon(),
        quality=QualityCanon(),
        display=DisplayCanon(
            colors=ColorsCanon(tokens=color_tokens),
            labels=LabelsCanon(error_messages=dict(VALIDATION_ERROR_MESSAGES)),
        ),
    )


def _convert_section_ops(
    raw: dict[str, list[tuple]],
) -> list[OperationDef]:
    """Конвертирует tuple-based SECTION_OPS в typed OperationDef."""
    result: list[OperationDef] = []
    for section_code, ops_list in raw.items():
        for tup in ops_list:
            (
                group_code,
                group_name,
                sort_order,
                op_code,
                op_name,
                is_sig,
                icon,
                icon_color,
                resolver_type,
                resolver_config,
                operation_type,
            ) = tup
            result.append(
                OperationDef(
                    section_code=section_code,
                    group_code=group_code,
                    group_name=group_name,
                    sort_order=sort_order,
                    operation_code=op_code,
                    operation_name=op_name,
                    is_significant=is_sig,
                    icon=icon,
                    icon_color=icon_color,
                    resolver_type=resolver_type,
                    resolver_config=resolver_config or {},
                    operation_type=operation_type,
                )
            )
    return result


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


def _validate_sections_cross_ref(
    sections: list[SectionDef],
    ops: list[OperationDef],
    transforming_ops: list[TransformingOpRef],
) -> None:
    """Cross-ref: sections ↔ ops ↔ transforming_ops (правила 1, 2, 4)."""
    section_codes = {s.code for s in sections}

    # Правило 2: нет дублей code в sections
    if len(section_codes) != len(sections):
        raise ValueError("Duplicate section codes detected")

    # Правило 1: все section_code в ops существуют в sections
    for op in ops:
        if op.section_code not in section_codes:
            raise ValueError(
                f"Operation '{op.operation_code}' references unknown "
                f"section '{op.section_code}'"
            )

    # Правило 4: operation_code уникален в рамках section
    seen_ops: set[tuple[str, str]] = set()
    for op in ops:
        if op.operation_code is None:
            continue
        key = (op.section_code, op.operation_code)
        if key in seen_ops:
            raise ValueError(
                f"Duplicate operation_code '{op.operation_code}' "
                f"in section '{op.section_code}'"
            )
        seen_ops.add(key)

    # Правило 1+4: transforming_ops ссылаются на существующие (section, op)
    for ref in transforming_ops:
        if ref.section_code not in section_codes:
            raise ValueError(
                f"TransformingOpRef references unknown section '{ref.section_code}'"
            )
        if (ref.section_code, ref.operation_code) not in seen_ops:
            raise ValueError(
                f"TransformingOpRef references unknown operation "
                f"'{ref.operation_code}' in section '{ref.section_code}'"
            )
