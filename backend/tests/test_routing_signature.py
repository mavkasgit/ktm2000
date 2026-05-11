import pytest

from app.models.routing import RouteOperationFamily, RouteOutputKind
from app.services.routing_signature import (
    canonical_signature_from_payload,
    normalize_operation_family,
    normalize_output_kind,
    normalize_pack_op_family,
)


@pytest.mark.parametrize(
    "raw_op,op_code,expected_family",
    [
        ("", None, RouteOperationFamily.NONE),
        ("сверло", None, RouteOperationFamily.DRILL),
        ("окно", None, RouteOperationFamily.PRESS),
        ("гребенка", None, RouteOperationFamily.PRESS),
        ("клей", None, RouteOperationFamily.PACK),
        ("рассеиватель", None, RouteOperationFamily.PACK),
        ("Без рассеивателя", None, RouteOperationFamily.PACK),
        ("", "PRESS_WINDOW", RouteOperationFamily.PRESS),
        ("", "PRESS_COMB", RouteOperationFamily.PRESS),
        ("", "DRILL", RouteOperationFamily.DRILL),
    ],
)
def test_normalize_operation_family(raw_op, op_code, expected_family):
    assert normalize_operation_family(operation_code=op_code, raw_operation=raw_op) == expected_family


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ГП", RouteOutputKind.finished_good),
        ("П/ф", RouteOutputKind.semi_finished_shipment),
        ("finished_good", RouteOutputKind.finished_good),
        ("semi_finished_shipment", RouteOutputKind.semi_finished_shipment),
    ],
)
def test_normalize_output_kind(raw, expected):
    assert normalize_output_kind(raw) == expected


def test_normalize_pack_op_family_no_diffuser_is_custom():
    assert normalize_pack_op_family("Без рассеивателя") == "CUSTOM"


def test_canonical_signature_from_payload():
    payload = {
        "operation_code": "PRESS_WINDOW",
        "operation": "окно",
        "output_kind": "finished_good",
        "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
    }
    signature = canonical_signature_from_payload(payload)
    assert signature is not None
    assert signature.operation_family == RouteOperationFamily.PRESS
    assert signature.output_kind == RouteOutputKind.finished_good
    assert signature.has_pack_ops is True
