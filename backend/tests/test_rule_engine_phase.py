"""Tests for the unified rule engine with phase support and DSL actions."""

import pytest

from app.services.route_selection import (
    _set_nested,
    _add_to_nested,
    _remove_from_nested,
    _apply_dsl_action,
    _load_rules_by_phase,
    _normalize_template_mapping,
    build_route_rule_context,
)


class TestNestedContextHelpers:
    def test_set_nested_simple(self):
        ctx = {}
        _set_nested(ctx, ["test_field"], "hello")
        assert ctx == {"test_field": "hello"}

    def test_set_nested_dotted(self):
        ctx = {}
        _set_nested(ctx, ["required_sections"], [1, 2, 3])
        assert ctx == {"required_sections": [1, 2, 3]}

    def test_set_nested_deep(self):
        ctx = {}
        _set_nested(ctx, ["routing", "priority"], "high")
        assert ctx == {"routing": {"priority": "high"}}

    def test_set_nested_overwrite(self):
        ctx = {"key": "old"}
        _set_nested(ctx, ["key"], "new")
        assert ctx == {"key": "new"}

    def test_add_to_nested_creates_list(self):
        ctx = {}
        _add_to_nested(ctx, ["tags"], "first")
        assert ctx == {"tags": ["first"]}

    def test_add_to_nested_appends(self):
        ctx = {"tags": ["first"]}
        _add_to_nested(ctx, ["tags"], "second")
        assert ctx == {"tags": ["first", "second"]}

    def test_add_to_nested_converts_scalar_to_list(self):
        ctx = {"tags": "existing"}
        _add_to_nested(ctx, ["tags"], "new")
        assert ctx == {"tags": ["existing", "new"]}

    def test_remove_from_nested_list(self):
        ctx = {"tags": ["a", "b", "c"]}
        _remove_from_nested(ctx, ["tags"], "b")
        assert ctx == {"tags": ["a", "c"]}

    def test_remove_from_nested_empty_deletes_key(self):
        ctx = {"tags": ["a"]}
        _remove_from_nested(ctx, ["tags"], "a")
        assert "tags" not in ctx

    def test_remove_from_nested_scalar(self):
        ctx = {"key": "value"}
        _remove_from_nested(ctx, ["key"], "value")
        assert "key" not in ctx

    def test_remove_from_nested_missing_path(self):
        ctx = {}
        _remove_from_nested(ctx, ["a", "b"], "value")
        assert ctx == {}


class TestApplyDslAction:
    def test_set_action(self):
        ctx = {}
        result = _apply_dsl_action(ctx, {"action": "set", "path": "ctx.operation_type", "value": "press"})
        assert result == {"action": "set", "path": "ctx.operation_type", "value": "press"}
        assert ctx == {"operation_type": "press"}

    def test_add_action(self):
        ctx = {}
        _apply_dsl_action(ctx, {"action": "add", "path": "ctx.tags", "value": "tag1"})
        _apply_dsl_action(ctx, {"action": "add", "path": "ctx.tags", "value": "tag2"})
        assert ctx == {"tags": ["tag1", "tag2"]}

    def test_remove_action(self):
        ctx = {"tags": ["a", "b"]}
        result = _apply_dsl_action(ctx, {"action": "remove", "path": "ctx.tags", "value": "a"})
        assert result is not None
        assert ctx == {"tags": ["b"]}

    def test_invalid_path_rejected(self):
        ctx = {}
        result = _apply_dsl_action(ctx, {"action": "set", "path": "payload.field", "value": "x"})
        assert result is None

    def test_set_required_sections(self):
        ctx = {}
        _apply_dsl_action(ctx, {"action": "set", "path": "ctx.required_sections", "value": [1, 2]})
        assert ctx["required_sections"] == [1, 2]


class TestLoadRulesByPhase:
    def test_route_select_default(self):
        """Rules without phase attribute default to route_select."""
        class FakeRule:
            def __init__(self):
                pass
        rules = [FakeRule()]
        select_rules = _load_rules_by_phase(rules, "route_select")
        assert len(select_rules) == 1

    def test_normalize_filtered(self):
        """Rules without phase are not selected for normalize phase."""
        class FakeRule:
            def __init__(self):
                pass
        rules = [FakeRule()]
        normalize_rules = _load_rules_by_phase(rules, "normalize")
        assert len(normalize_rules) == 0

    def test_phase_attribute_respected(self):
        """Rules with phase attribute are filtered correctly."""
        class FakeRule:
            def __init__(self, phase):
                self.phase = phase
        rules = [FakeRule("normalize"), FakeRule("route_select")]
        normalize_rules = _load_rules_by_phase(rules, "normalize")
        assert len(normalize_rules) == 1
        assert normalize_rules[0].phase == "normalize"


class TestBuildContext:
    def test_ctx_is_empty_dict(self):
        context = build_route_rule_context({})
        assert context["ctx"] == {}

    def test_ctx_is_independent(self):
        context1 = build_route_rule_context({})
        context2 = build_route_rule_context({})
        context1["ctx"]["key"] = "value"
        assert context2["ctx"] == {}


class TestTemplateMappingNormalization:
    def test_supports_object_mapping_values(self):
        normalized = _normalize_template_mapping(
            {
                "sku": {"header": "Артикул", "column": "A"},
                "output_kind": {"header": "Вид конечного продукта", "column": "O"},
            }
        )
        assert normalized == {
            "sku": "Артикул",
            "output_kind": "Вид конечного продукта",
        }

    def test_drops_invalid_entries(self):
        normalized = _normalize_template_mapping(
            {
                "": {"header": "Артикул"},
                "operation": {"column": "H"},
                "priority": None,
                "output_kind": "Вид конечного продукта",
            }
        )
        assert normalized == {"output_kind": "Вид конечного продукта"}
