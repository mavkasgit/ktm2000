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
    RouteRuleProfileDef,
    RoutingCanon,
    SPGDef,
    SectionDef,
    SelectionRuleDef,
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
    from app.seeds.import_templates import IMPORT_TEMPLATES
    from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
    from app.seeds.selection_rules import SELECTION_RULES
    from app.seeds.seeders.sections_seeder import (
        SECTIONS_DATA,
        SECTION_OPS,
        TRANSFORMING_SECTION_OPS,
    )
    from app.seeds.spgs import SPGS_DATA

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

    routing = _build_routing_canon(
        selection_rules=[SelectionRuleDef.model_validate(d) for d in SELECTION_RULES],
        route_rule_profiles=[RouteRuleProfileDef.model_validate(d) for d in ROUTE_RULE_PROFILES],
        spgs=[SPGDef.model_validate(d) for d in SPGS_DATA],
        import_template_codes=[t["code"] for t in IMPORT_TEMPLATES],
        section_codes=[s.code for s in sections],
    )

    quality = _build_quality_canon()

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
        routing=routing,
        quality=quality,
        display=DisplayCanon(
            colors=ColorsCanon(tokens=color_tokens),
            labels=LabelsCanon(error_messages=dict(VALIDATION_ERROR_MESSAGES)),
        ),
    )


def _build_quality_canon() -> QualityCanon:
    """Собирает QualityCanon и проверяет cross-ref правила 2, 3, 6."""
    from app.seeds.canon.quality_data import DEFECT_DECISION_MAP, DEFECT_TYPES

    defect_type_codes = [t.code for t in DEFECT_TYPES]
    _validate_unique_codes(defect_type_codes, "defect type")

    # Правило 6: enum-поля (decision key, status, reason) — допустимые значения
    decision_keys = {
        "scrap",
        "rework_current",
        "return_previous",
        "accept_with_deviation",
    }
    statuses = {
        "open",
        "decision_required",
        "rework_task_created",
        "scrapped",
        "returned",
        "accepted_with_deviation",
        "closed",
    }
    reasons = {"complete", "return_to_previous", "scrap", "rework"}
    for decision, entry in DEFECT_DECISION_MAP.mapping.items():
        if decision not in decision_keys:
            raise ValueError(f"Unknown defect decision code: {decision!r}")
        if entry.status not in statuses:
            raise ValueError(
                f"Defect decision '{decision}' maps to unknown status {entry.status!r}"
            )
        if entry.reason is not None and entry.reason not in reasons:
            raise ValueError(
                f"Defect decision '{decision}' maps to unknown reason {entry.reason!r}"
            )
        # Правило 3: обязательные поля не пустые
        if not entry.status.strip():
            raise ValueError(f"Defect decision '{decision}' has blank status")

    return QualityCanon(
        defect_decision_map=DEFECT_DECISION_MAP,
        defect_types=DEFECT_TYPES,
    )


def _build_routing_canon(
    *,
    selection_rules: list[SelectionRuleDef],
    route_rule_profiles: list[RouteRuleProfileDef],
    spgs: list[SPGDef],
    import_template_codes: list[str],
    section_codes: list[str],
) -> RoutingCanon:
    """Собирает RoutingCanon и проверяет cross-ref правила 1, 2, 5, 6, 7."""
    section_set = set(section_codes)

    # Правило 2: нет дублей code в каждом наборе
    _validate_unique_codes([r.code for r in selection_rules], "selection rule")
    _validate_unique_codes([p.code for p in route_rule_profiles], "route rule profile")
    _validate_unique_codes([s.code for s in spgs], "SPG")

    profile_codes = {p.code for p in route_rule_profiles}
    template_codes = set(import_template_codes)

    # Правило 5: import_template_code в профиле существует в IMPORT_TEMPLATES
    for profile in route_rule_profiles:
        if profile.import_template_code and profile.import_template_code not in template_codes:
            raise ValueError(
                f"Profile '{profile.code}' references unknown import template "
                f"'{profile.import_template_code}'"
            )
        for section_code in profile.route_sections:
            if section_code not in section_set:
                raise ValueError(
                    f"Profile '{profile.code}' references unknown section "
                    f"'{section_code}' in route_sections"
                )

    # Правило 1: profile_code в rules существует в profiles;
    # section_code в actions существует в sections
    for rule in selection_rules:
        if rule.profile_code not in profile_codes:
            raise ValueError(
                f"Selection rule '{rule.code}' references unknown profile "
                f"'{rule.profile_code}'"
            )
        for action in rule.actions:
            section_code = getattr(action, "section_code", None)
            if section_code and section_code not in section_set:
                raise ValueError(
                    f"Selection rule '{rule.code}' action '{action.action}' "
                    f"references unknown section '{section_code}'"
                )

    # SPG: section_codes существуют в sections
    for spg in spgs:
        for section_code in spg.section_codes:
            if section_code not in section_set:
                raise ValueError(
                    f"SPG '{spg.code}' references unknown section '{section_code}'"
                )

    return RoutingCanon(
        selection_rules=selection_rules,
        route_rule_profiles=route_rule_profiles,
        spgs=spgs,
    )


def _validate_unique_codes(codes: list[str], kind: str) -> None:
    """Правило 2: нет дублей code в наборе."""
    if len(codes) != len(set(codes)):
        seen: set[str] = set()
        for code in codes:
            if code in seen:
                raise ValueError(f"Duplicate {kind} code: {code!r}")
            seen.add(code)


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
