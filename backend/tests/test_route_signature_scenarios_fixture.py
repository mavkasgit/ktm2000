import json
from pathlib import Path

from app.services.excel_import import _normalize_operation, _normalize_output_kind
from app.services.routing_signature import canonical_signature_from_payload


def test_route_signature_fixture_contains_regular_and_paired_scenarios():
    fixture_path = Path(__file__).resolve().parents[1] / "data" / "route_signature_scenarios.json"
    scenarios = json.loads(fixture_path.read_text(encoding="utf-8"))

    signatures = set()
    paired = [s for s in scenarios if s.get("scenario_group") == "paired_profile"]
    regular = [s for s in scenarios if s.get("scenario_group") != "paired_profile"]

    assert paired, "Paired profile scenario must be present"
    for scenario in paired:
        assert scenario.get("primary_sku")
        assert scenario.get("secondary_sku")

    for scenario in scenarios:
        op_code, _op_name, add_pack = _normalize_operation(scenario.get("operation_raw"))
        payload = {
            "operation": scenario.get("operation_raw"),
            "operation_code": op_code,
            "output_kind": _normalize_output_kind(scenario.get("output_kind_raw")),
            "additional_pack_operations": add_pack,
        }
        signature = canonical_signature_from_payload(payload)
        assert signature is not None
        signatures.add((signature.operation_family.value, signature.output_kind.value, signature.has_pack_ops))

    assert len(regular) == 11
    assert len(scenarios) == 12
    assert len(signatures) == 8
