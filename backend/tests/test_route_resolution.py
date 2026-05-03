import pytest
from app.services.route_resolution import resolve_route_signature, RouteStepSignature


@pytest.mark.parametrize(
    "payload,expected_steps",
    [
        # 1. NONE -> semi_finished_shipment
        (
            {
                "operation_code": None,
                "output_kind": "semi_finished_shipment",
                "additional_pack_operations": [],
                "paired_profile": False,
            },
            ["WH/ISSUE_RAW", "SHOT", "ANOD", "FG_WH/ACCEPT_FINISHED"],
        ),
        # 2. DRILL -> finished_good
        (
            {
                "operation_code": "DRILL",
                "output_kind": "finished_good",
                "additional_pack_operations": [],
                "paired_profile": False,
            },
            [
                "WH/ISSUE_RAW",
                "DRILL",
                "SHOT",
                "ANOD",
                "WIP_WH/MOVE_TO_WIP",
                "SAW",
                "PACK",
                "FG_WH/ACCEPT_FINISHED",
            ],
        ),
        # 3. PRESS_WINDOW + PACK_GLUE -> finished_good
        (
            {
                "operation_code": "PRESS_WINDOW",
                "output_kind": "finished_good",
                "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
                "paired_profile": False,
            },
            [
                "WH/ISSUE_RAW",
                "PRESS_WINDOW",
                "SHOT",
                "ANOD",
                "WIP_WH/MOVE_TO_WIP",
                "SAW",
                "PACK",
                "FG_WH/ACCEPT_FINISHED",
            ],
        ),
        # 4. PRESS_COMB + PACK_DIFFUSER -> finished_good
        (
            {
                "operation_code": "PRESS_COMB",
                "output_kind": "finished_good",
                "additional_pack_operations": [{"operation_code": "PACK_DIFFUSER"}],
                "paired_profile": False,
            },
            [
                "WH/ISSUE_RAW",
                "PRESS_COMB",
                "SHOT",
                "ANOD",
                "WIP_WH/MOVE_TO_WIP",
                "SAW",
                "PACK",
                "FG_WH/ACCEPT_FINISHED",
            ],
        ),
        # 5. NONE -> finished_good (no primary operation)
        (
            {
                "operation_code": None,
                "output_kind": "finished_good",
                "additional_pack_operations": [],
                "paired_profile": False,
            },
            [
                "WH/ISSUE_RAW",
                "SHOT",
                "ANOD",
                "WIP_WH/MOVE_TO_WIP",
                "SAW",
                "PACK",
                "FG_WH/ACCEPT_FINISHED",
            ],
        ),
    ],
)
def test_resolve_route_signature(payload, expected_steps):
    result = resolve_route_signature(payload)
    assert [step.step_id for step in result.steps] == expected_steps
    assert result.primary_operation == payload["operation_code"]
    assert result.output_kind == payload["output_kind"]
    assert result.additional_pack_operations == [
        op["operation_code"] for op in payload["additional_pack_operations"] if "operation_code" in op
    ]


def test_route_step_signature_defaults():
    step = RouteStepSignature(step_id="WH/ISSUE_RAW")
    assert step.operation_code is None
    assert step.section_kind is None
    assert step.description == ""
