from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_IMPORT_NORMALIZATION_RULES: dict[str, Any] = {
    "version": 1,
    "operation": {
        "rules": [
            {
                "priority": 100,
                "contains": ["без рассеив"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_CUSTOM",
                            "operation_name_template": "Доп. упаковочная операция: {raw}",
                        }
                    ],
                    "normalized_pack_op_family": "CUSTOM",
                },
            },
            {
                "priority": 90,
                "contains": ["окн"],
                "result": {
                    "operation_code": "PRESS_WINDOW",
                    "operation_name": "Пресс окно",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 80,
                "contains": ["греб"],
                "result": {
                    "operation_code": "PRESS_COMB",
                    "operation_name": "Пресс гребенка",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 70,
                "contains": ["сверл", "сверло"],
                "result": {
                    "operation_code": "DRILL",
                    "operation_name": "Сверловка",
                    "additional_pack_operations": [],
                    "normalized_pack_op_family": "NONE",
                },
            },
            {
                "priority": 60,
                "contains": ["клей"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_GLUE",
                            "operation_name": "Упаковка с клеевой операцией",
                        }
                    ],
                    "normalized_pack_op_family": "GLUE",
                },
            },
            {
                "priority": 50,
                "contains": ["рассеив"],
                "result": {
                    "operation_code": "PACK",
                    "operation_name": "Упаковка",
                    "additional_pack_operations": [
                        {
                            "operation_code": "PACK_DIFFUSER",
                            "operation_name": "Упаковка с рассеивателем",
                        }
                    ],
                    "normalized_pack_op_family": "DIFFUSER",
                },
            },
        ],
        "fallback": {
            "operation_code": "PACK",
            "operation_name": "Упаковка",
            "additional_pack_operations": [
                {
                    "operation_code": "PACK_CUSTOM",
                    "operation_name_template": "Доп. упаковочная операция: {raw}",
                }
            ],
            "normalized_pack_op_family": "CUSTOM",
        },
    },
    "output_kind": {
        "rules": [
            {"priority": 100, "contains": ["гп", "гп."], "result": "finished_good"},
            {"priority": 90, "contains": ["пф", "пф."], "result": "semi_finished_shipment"},
        ],
        "fallback": "raw",
    },
}


def default_import_normalization_rules() -> dict[str, Any]:
    return deepcopy(DEFAULT_IMPORT_NORMALIZATION_RULES)


def has_valid_normalization_rules(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    operation = value.get("operation")
    output_kind = value.get("output_kind")
    if not isinstance(operation, dict) or not isinstance(output_kind, dict):
        return False
    if not isinstance(operation.get("rules"), list) or not operation.get("fallback"):
        return False
    if not isinstance(output_kind.get("rules"), list) or "fallback" not in output_kind:
        return False
    return True


def apply_import_normalization(
    *,
    raw_operation: str | None,
    raw_output_kind: str | None,
    normalization_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    rules = normalization_rules if has_valid_normalization_rules(normalization_rules) else {}
    operation_rules = rules.get("operation") if isinstance(rules, dict) else None
    output_kind_rules = rules.get("output_kind") if isinstance(rules, dict) else None

    operation_result = _resolve_operation(raw_operation, operation_rules)
    output_kind_result = _resolve_output_kind(raw_output_kind, output_kind_rules)

    return {
        "operation_code": operation_result.get("operation_code"),
        "operation_name": operation_result.get("operation_name"),
        "additional_pack_operations": operation_result.get("additional_pack_operations", []),
        "normalized_pack_op_family": operation_result.get("normalized_pack_op_family", "NONE"),
        "output_kind": output_kind_result,
    }


def _resolve_operation(raw_value: str | None, operation_rules: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_value:
        return {
            "operation_code": None,
            "operation_name": None,
            "additional_pack_operations": [],
            "normalized_pack_op_family": "NONE",
        }

    normalized = raw_value.lower().replace("ё", "е").strip()
    chosen = _match_rule(normalized, operation_rules.get("rules") if isinstance(operation_rules, dict) else None)
    fallback = operation_rules.get("fallback") if isinstance(operation_rules, dict) else None
    result = chosen.get("result") if isinstance(chosen, dict) else fallback
    if not isinstance(result, dict):
        return {
            "operation_code": None,
            "operation_name": None,
            "additional_pack_operations": [],
            "normalized_pack_op_family": "NONE",
        }

    additional = _render_pack_operations(result.get("additional_pack_operations"), raw_value)
    return {
        "operation_code": _str_or_none(result.get("operation_code")),
        "operation_name": _str_or_none(result.get("operation_name")),
        "additional_pack_operations": additional,
        "normalized_pack_op_family": _str_or_none(result.get("normalized_pack_op_family")) or "NONE",
    }


def _resolve_output_kind(raw_value: str | None, output_kind_rules: dict[str, Any] | None) -> str | None:
    if not raw_value:
        return None

    normalized = raw_value.lower().replace("/", "").replace(" ", "")
    chosen = _match_rule(normalized, output_kind_rules.get("rules") if isinstance(output_kind_rules, dict) else None)
    if isinstance(chosen, dict):
        result = _str_or_none(chosen.get("result"))
        if result:
            return result

    fallback = output_kind_rules.get("fallback") if isinstance(output_kind_rules, dict) else "raw"
    if fallback == "raw":
        return raw_value
    fallback_value = _str_or_none(fallback)
    return fallback_value or raw_value


def _match_rule(normalized_text: str, rules: Any) -> dict[str, Any] | None:
    if not isinstance(rules, list):
        return None

    sorted_rules = sorted(
        [rule for rule in rules if isinstance(rule, dict)],
        key=lambda item: int(item.get("priority", 0)),
        reverse=True,
    )
    for rule in sorted_rules:
        contains = rule.get("contains")
        tokens: list[str]
        if isinstance(contains, str):
            tokens = [contains]
        elif isinstance(contains, list):
            tokens = [str(item) for item in contains if str(item).strip()]
        else:
            tokens = []
        if not tokens:
            continue
        if any(token.lower().replace("ё", "е").strip() in normalized_text for token in tokens):
            return rule
    return None


def _render_pack_operations(value: Any, raw_text: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        operation_code = _str_or_none(item.get("operation_code"))
        if not operation_code:
            continue
        operation_name = _str_or_none(item.get("operation_name"))
        operation_name_template = _str_or_none(item.get("operation_name_template"))
        if not operation_name and operation_name_template:
            operation_name = operation_name_template.replace("{raw}", raw_text)
        result.append(
            {
                "operation_code": operation_code,
                "operation_name": operation_name or operation_code,
            }
        )
    return result


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
