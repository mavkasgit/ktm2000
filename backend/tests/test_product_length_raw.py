"""Публичный API-контракт реестра нормальных и сырьевых длин."""
from __future__ import annotations

import pytest


def _linear_payload(
    sku: str,
    *,
    length_mm: float = 2700,
    raw_length_mm: float | None = None,
    is_primary: bool = True,
    **overrides,
) -> dict:
    payload = {
        "sku": sku,
        "name": sku,
        "type": "component",
        "unit": "pcs",
        "lengths": [
            {
                "length_mm": length_mm,
                "raw_length_mm": raw_length_mm,
                "is_primary": is_primary,
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_linear_length_registry_create_read_and_patch(client) -> None:
    """Реестр сохраняет канонический порядок, primary и различия omitted/null для raw."""
    created = await client.post(
        "/api/products",
        json={
            "sku": "RAW-LENGTH-REGISTRY",
            "name": "Линейный артикул с реестром длин",
            "type": "component",
            "unit": "pcs",
            "lengths": [
                {"length_mm": 4000, "raw_length_mm": None, "is_primary": False},
                {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
                {"length_mm": 3500, "raw_length_mm": 3550, "is_primary": False},
            ],
        },
    )

    assert created.status_code == 201, created.text
    expected_created = [
        {"length_mm": 2700.0, "raw_length_mm": 2750.0, "is_primary": True},
        {"length_mm": 3500.0, "raw_length_mm": 3550.0, "is_primary": False},
        {"length_mm": 4000.0, "raw_length_mm": None, "is_primary": False},
    ]
    assert created.json()["lengths"] == expected_created

    product_id = created.json()["id"]
    read = await client.get(f"/api/products/{product_id}")

    assert read.status_code == 200, read.text
    assert read.json()["lengths"] == expected_created

    patched = await client.patch(
        f"/api/products/{product_id}",
        json={
            "lengths": [
                {"length_mm": 2700, "is_primary": False},
                {"length_mm": 3500, "raw_length_mm": None, "is_primary": True},
                {"length_mm": 4000, "raw_length_mm": 4080, "is_primary": False},
            ]
        },
    )

    assert patched.status_code == 200, patched.text
    expected_patched = [
        {"length_mm": 2700.0, "raw_length_mm": 2750.0, "is_primary": False},
        {"length_mm": 3500.0, "raw_length_mm": None, "is_primary": True},
        {"length_mm": 4000.0, "raw_length_mm": 4080.0, "is_primary": False},
    ]
    assert patched.json()["lengths"] == expected_patched

    read_after_patch = await client.get(f"/api/products/{product_id}")
    assert read_after_patch.status_code == 200, read_after_patch.text
    assert read_after_patch.json()["lengths"] == expected_patched


@pytest.mark.asyncio
async def test_create_persists_auto_hanger_quantity_from_raw_length(client) -> None:
    """Авто-норма подвеса сохраняется по сырьевой, а не нормальной длине."""
    response = await client.post(
        "/api/products",
        json=_linear_payload(
            "RAW-LENGTH-HANGER-AUTO",
            length_mm=3000,
            raw_length_mm=3050,
            perimeter_mm=60,
            mount_width_mm=15,
            hanger_mode="auto",
        ),
    )

    assert response.status_code == 201, response.text
    assert response.json()["quantity_per_hanger"] == {
        "3000": {"auto": 71, "manual": None}
    }

@pytest.mark.asyncio
async def test_create_and_read_linear_product_with_raw_length(client) -> None:
    response = await client.post(
        "/api/products",
        json=_linear_payload("RAW-LENGTH-2700", raw_length_mm=2750),
    )

    assert response.status_code == 201, response.text
    expected = [
        {"length_mm": 2700.0, "raw_length_mm": 2750.0, "is_primary": True}
    ]
    assert response.json()["lengths"] == expected

    product_id = response.json()["id"]
    read_response = await client.get(f"/api/products/{product_id}")

    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["lengths"] == expected


@pytest.mark.asyncio
async def test_raw_length_null_is_preserved_for_normal_length_fallback(client) -> None:
    response = await client.post(
        "/api/products",
        json=_linear_payload("RAW-LENGTH-FALLBACK", raw_length_mm=None),
    )

    assert response.status_code == 201, response.text
    expected = [
        {"length_mm": 2700.0, "raw_length_mm": None, "is_primary": True}
    ]
    assert response.json()["lengths"] == expected

    read_response = await client.get(f"/api/products/{response.json()['id']}")

    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["lengths"] == expected


@pytest.mark.asyncio
async def test_raw_length_less_than_normal_is_rejected(client) -> None:
    response = await client.post(
        "/api/products",
        json=_linear_payload("RAW-LENGTH-TOO-SHORT", raw_length_mm=2699),
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "lengths",
    [
        pytest.param(
            [
                {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
                {"length_mm": 2700, "raw_length_mm": 2800, "is_primary": False},
            ],
            id="duplicate-normal-length",
        ),
        pytest.param(
            [
                {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True},
                {"length_mm": 3500, "raw_length_mm": 3550, "is_primary": True},
            ],
            id="multiple-primary-lengths",
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_linear_length_registry_is_rejected(client, lengths: list[dict]) -> None:
    response = await client.post(
        "/api/products",
        json={
            "sku": "RAW-LENGTH-INVALID",
            "name": "Raw length invalid",
            "type": "component",
            "unit": "pcs",
            "lengths": lengths,
        },
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_patch_with_omitted_raw_length_preserves_existing_value(client) -> None:
    created = await client.post(
        "/api/products",
        json=_linear_payload("RAW-LENGTH-PATCH-PRESERVE", raw_length_mm=2750),
    )
    assert created.status_code == 201, created.text

    response = await client.patch(
        f"/api/products/{created.json()['id']}",
        json={"lengths": [{"length_mm": 2700, "is_primary": True}]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["lengths"] == [
        {"length_mm": 2700.0, "raw_length_mm": 2750.0, "is_primary": True}
    ]


@pytest.mark.asyncio
async def test_patch_normal_increase_above_raw_clears_raw_length(client) -> None:
    created = await client.post(
        "/api/products",
        json=_linear_payload("RAW-LENGTH-PATCH-CLEAR", raw_length_mm=2750),
    )
    assert created.status_code == 201, created.text

    response = await client.patch(
        f"/api/products/{created.json()['id']}",
        json={"lengths": [{"length_mm": 2800, "is_primary": True}]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["lengths"] == [
        {"length_mm": 2800.0, "raw_length_mm": None, "is_primary": True}
    ]


@pytest.mark.parametrize("dimension_state", ["area", "volume"])
@pytest.mark.asyncio
async def test_non_linear_product_rejects_raw_length(client, dimension_state: str) -> None:
    response = await client.post(
        "/api/products",
        json={
            "sku": f"RAW-LENGTH-{dimension_state.upper()}",
            "name": f"Non-linear {dimension_state}",
            "type": "component",
            "unit": "pcs",
            "dimension_state": dimension_state,
            "lengths": [
                {"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}
            ],
        },
    )

    assert response.status_code == 422, response.text
