"""Gate-тест целостности сидов (ADR-0004, тикет #22).

Запускается первым в CI. Проверяет, что build_plant_config() собирается
из РЕАЛЬНЫХ данных и все cross-ref правила проходят.
"""

from __future__ import annotations

import pytest

from app.seeds.canon import build_plant_config
from app.seeds.canon.models import PlantConfig


class TestSeedIntegrity:
    """build_plant_config() собирается, cross-ref проходят."""

    def test_build_plant_config_succeeds(self) -> None:
        """PlantConfig собирается из реальных данных без ошибок."""
        config = build_plant_config()
        assert isinstance(config, PlantConfig)

    def test_color_tokens_non_empty(self) -> None:
        """Цветовые токены загружены."""
        config = build_plant_config()
        assert len(config.display.colors.tokens) > 0

    def test_color_tokens_no_duplicates(self) -> None:
        """Правило 2: нет дублей token в наборе."""
        config = build_plant_config()
        tokens = [t.token for t in config.display.colors.tokens]
        assert len(tokens) == len(set(tokens))

    def test_color_tokens_required_fields(self) -> None:
        """Правило 3: обязательные поля не пустые."""
        config = build_plant_config()
        for t in config.display.colors.tokens:
            assert t.token.strip()
            assert t.color.strip()

    def test_error_messages_non_empty(self) -> None:
        """Тексты ошибок валидации загружены."""
        config = build_plant_config()
        assert len(config.display.labels.error_messages) > 0

    def test_error_messages_keys_non_blank(self) -> None:
        """Правило 3: ключи error_messages не пустые."""
        config = build_plant_config()
        for key in config.display.labels.error_messages:
            assert key.strip()

    def test_hanger_rounding_enum_valid(self) -> None:
        """Правило 6: mode содержит допустимое значение."""
        config = build_plant_config()
        assert config.production.hanger_rounding.mode == "round_up_to_multiple"

    def test_processing_flags_non_empty(self) -> None:
        """Правило 3: значения флагов обработки не пустые."""
        config = build_plant_config()
        assert config.production.processing_flags.paired.strip()
        assert config.production.processing_flags.standart.strip()

    def test_config_is_immutable_snapshot(self) -> None:
        """Два вызова дают эквивалентный результат (детерминизм)."""
        c1 = build_plant_config()
        c2 = build_plant_config()
        assert c1 == c2

    # ─── Sections + Ops cross-ref (тикет #23) ─────────────────────────────

    def test_sections_non_empty(self) -> None:
        """Участки загружены."""
        config = build_plant_config()
        assert len(config.production.sections) > 0

    def test_sections_no_duplicate_codes(self) -> None:
        """Правило 2: нет дублей code в sections."""
        config = build_plant_config()
        codes = [s.code for s in config.production.sections]
        assert len(codes) == len(set(codes))

    def test_ops_reference_valid_sections(self) -> None:
        """Правило 1: все section_code в ops существуют в sections."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        for op in config.production.ops:
            assert op.section_code in section_codes, (
                f"Op '{op.operation_code}' → unknown section '{op.section_code}'"
            )

    def test_ops_unique_within_section(self) -> None:
        """Правило 4: operation_code уникален в рамках section."""
        config = build_plant_config()
        seen: set[tuple[str, str]] = set()
        for op in config.production.ops:
            if op.operation_code is None:
                continue
            key = (op.section_code, op.operation_code)
            assert key not in seen, f"Duplicate op: {key}"
            seen.add(key)

    def test_transforming_ops_reference_valid(self) -> None:
        """TransformingOpRef ????????? ?? ???????????? (section, op)."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        op_keys = {
            (op.section_code, op.operation_code)
            for op in config.production.ops
            if op.operation_code is not None
        }
        for ref in config.production.transforming_ops:
            assert ref.section_code in section_codes
            assert (ref.section_code, ref.operation_code) in op_keys


class TestRoutingCanonIntegrity:
    """Routing canon (тикет #24): selection rules, profiles, SPG."""

    def test_routing_loaded(self) -> None:
        """RoutingCanon содержит правила, профили и SPG."""
        config = build_plant_config()
        assert len(config.routing.selection_rules) > 0
        assert len(config.routing.route_rule_profiles) > 0
        assert len(config.routing.spgs) > 0

    def test_rule_actions_are_typed(self) -> None:
        """JSONB actions типизированы (не dict)."""
        config = build_plant_config()
        for rule in config.routing.selection_rules:
            for action in rule.actions:
                assert hasattr(action, "action")

    def test_rule_profile_code_exists(self) -> None:
        """Правило 1: profile_code в rules существует в profiles."""
        config = build_plant_config()
        profile_codes = {p.code for p in config.routing.route_rule_profiles}
        for rule in config.routing.selection_rules:
            assert rule.profile_code in profile_codes, (
                f"Rule '{rule.code}' -> unknown profile '{rule.profile_code}'"
            )

    def test_rule_section_codes_exist(self) -> None:
        """Правило 1: section_code в actions существует в sections."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        for rule in config.routing.selection_rules:
            for action in rule.actions:
                section_code = getattr(action, "section_code", None)
                if section_code:
                    assert section_code in section_codes, (
                        f"Rule '{rule.code}' action '{action.action}' "
                        f"-> unknown section '{section_code}'"
                    )

    def test_rule_phase_is_valid_enum(self) -> None:
        """Правило 6: phase — только допустимые значения."""
        config = build_plant_config()
        allowed = {"normalize", "route_select", "resolve_operations", "resolve_signatures"}
        for rule in config.routing.selection_rules:
            assert rule.phase in allowed, f"Rule '{rule.code}' has invalid phase '{rule.phase}'"

    def test_rule_priorities_non_negative(self) -> None:
        """Правило 7: priority >= 0."""
        config = build_plant_config()
        for rule in config.routing.selection_rules:
            assert rule.priority >= 0, f"Rule '{rule.code}' has priority < 0"
        for profile in config.routing.route_rule_profiles:
            assert profile.priority >= 0, f"Profile '{profile.code}' has priority < 0"

    def test_no_duplicate_rule_codes(self) -> None:
        """Правило 2: нет дублей code в selection rules."""
        config = build_plant_config()
        codes = [r.code for r in config.routing.selection_rules]
        assert len(codes) == len(set(codes))

    def test_profile_template_code_exists(self) -> None:
        """Правило 5: import_template_code в профиле существует."""
        from app.seeds.import_templates import IMPORT_TEMPLATES

        config = build_plant_config()
        template_codes = {t["code"] for t in IMPORT_TEMPLATES}
        for profile in config.routing.route_rule_profiles:
            if profile.import_template_code:
                assert profile.import_template_code in template_codes, (
                    f"Profile '{profile.code}' -> unknown template "
                    f"'{profile.import_template_code}'"
                )

    def test_profile_route_sections_exist(self) -> None:
        """route_sections профиля ссылаются на существующие sections."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        for profile in config.routing.route_rule_profiles:
            for section_code in profile.route_sections:
                assert section_code in section_codes, (
                    f"Profile '{profile.code}' -> unknown section '{section_code}'"
                )

    def test_spg_sections_exist(self) -> None:
        """section_codes SPG ссылаются на существующие sections."""
        config = build_plant_config()
        section_codes = {s.code for s in config.production.sections}
        for spg in config.routing.spgs:
            for section_code in spg.section_codes:
                assert section_code in section_codes, (
                    f"SPG '{spg.code}' -> unknown section '{section_code}'"
                )

    def test_rule_conditions_typed(self) -> None:
        """Conditions типизированы: operator — допустимый enum."""
        from app.seeds.canon.models import ConditionOperator

        config = build_plant_config()
        allowed = set(ConditionOperator.__args__)
        for rule in config.routing.selection_rules:
            for condition in rule.conditions:
                assert condition.operator in allowed, (
                    f"Rule '{rule.code}' has invalid operator '{condition.operator}'"
                )


class TestRoutingCanonFailFast:
    """Cross-ref registry падает на битых данных (fail-fast, ADR-0004 п.4)."""

    def _build(self, **kwargs):
        from app.seeds.canon.registry import _build_routing_canon

        return _build_routing_canon(
            selection_rules=kwargs.get("selection_rules", []),
            route_rule_profiles=kwargs.get("route_rule_profiles", []),
            spgs=kwargs.get("spgs", []),
            import_template_codes=kwargs.get("import_template_codes", ["tpl"]),
            section_codes=kwargs.get("section_codes", ["RAW_STOCK", "ANODIZING"]),
        )

    def test_unknown_profile_code_raises(self) -> None:
        """Правило 1: rule со ссылкой на несуществующий profile падает."""
        from app.seeds.canon.models import SelectionRuleDef

        with pytest.raises(ValueError, match="unknown profile"):
            self._build(
                selection_rules=[
                    SelectionRuleDef(
                        code="r1",
                        name="Rule 1",
                        profile_code="missing_profile",
                        priority=10,
                        actions=[],
                    )
                ]
            )

    def test_unknown_section_in_action_raises(self) -> None:
        """Правило 1: action с несуществующим section_code падает."""
        from app.seeds.canon.models import (
            RequireSectionAction,
            RouteRuleProfileDef,
            SelectionRuleDef,
        )

        with pytest.raises(ValueError, match="unknown section"):
            self._build(
                selection_rules=[
                    SelectionRuleDef(
                        code="r2",
                        name="Rule 2",
                        profile_code="prof",
                        priority=10,
                        actions=[RequireSectionAction(section_code="NO_SUCH_SECTION")],
                    )
                ],
                route_rule_profiles=[
                    RouteRuleProfileDef(code="prof", name="Prof", priority=1),
                ],
            )

    def test_unknown_template_code_raises(self) -> None:
        """Правило 5: профиль со ссылкой на несуществующий шаблон падает."""
        from app.seeds.canon.models import RouteRuleProfileDef

        with pytest.raises(ValueError, match="unknown import template"):
            self._build(
                route_rule_profiles=[
                    RouteRuleProfileDef(
                        code="prof",
                        name="Prof",
                        import_template_code="no_such_template",
                    )
                ],
                import_template_codes=["tpl"],
            )

    def test_unknown_spg_section_raises(self) -> None:
        """Правило 1: SPG с несуществующей секцией падает."""
        from app.seeds.canon.models import SPGDef

        with pytest.raises(ValueError, match="unknown section"):
            self._build(
                spgs=[SPGDef(code="SPG", name="SPG", section_codes=["NO_SUCH"])],
                section_codes=["RAW_STOCK"],
            )

    def test_duplicate_rule_code_raises(self) -> None:
        """Правило 2: дубли code в правилах падают."""
        from app.seeds.canon.models import SelectionRuleDef

        dup = SelectionRuleDef(code="r", name="Rule", profile_code="prof", priority=1)
        with pytest.raises(ValueError, match="Duplicate selection rule code"):
            self._build(
                selection_rules=[dup, dup],
                route_rule_profiles=[],
            )

    def test_invalid_phase_rejected_by_model(self) -> None:
        """Правило 6: недопустимый phase не проходит pydantic-валидацию."""
        import pydantic

        from app.seeds.canon.models import SelectionRuleDef

        with pytest.raises(pydantic.ValidationError):
            SelectionRuleDef(
                code="r",
                name="Rule",
                profile_code="prof",
                priority=1,
                phase="not_a_phase",
            )
