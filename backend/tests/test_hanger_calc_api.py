"""Тесты эндпоинта POST /api/hanger-calc (#62).

Поведение через HTTP-контракт: batch-порядок = порядок items, single =
batch из 1, нерасчётные данные → is_calculable:false без исключений,
невалидные константы/кросс-поле → 422, константы доступны в ответе.
"""

import pytest


@pytest.mark.asyncio
async def test_single_item_customer_example(client):
    resp = await client.post(
        "/api/hanger-calc",
        json={
            "items": [{"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    (result,) = body["results"]
    assert result["by_area"] == 72
    assert result["by_size"] == 72
    assert result["total"] == 72
    assert result["limiter"] == "area"
    assert result["is_calculable"] is True
    assert result["area_m2"] == pytest.approx(0.17976)
    # Константы (read-only) доступны фронту в ответе
    assert body["hanger"] == {"area_limit_m2": 13.0, "rod_length_mm": 1450.0, "gap_mm": 20.0, "rod_count": 2}


@pytest.mark.asyncio
async def test_batch_preserves_request_order(client):
    items = [
        {"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800},
        {"perimeter_mm": 10, "mount_width_mm": 300, "length_mm": 1000},
        {"perimeter_mm": None, "mount_width_mm": None, "length_mm": None},
    ]
    resp = await client.post("/api/hanger-calc", json={"items": items})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["total"] for r in results] == [72, 8, None]
    assert results[0]["limiter"] == "area"
    assert results[1]["limiter"] == "size"
    assert results[2]["is_calculable"] is False
    assert results[2]["by_area"] is None
    assert results[2]["by_size"] is None
    assert results[2]["total"] is None
    assert results[2]["limiter"] is None
    assert results[2]["area_m2"] is None


@pytest.mark.asyncio
async def test_single_is_batch_of_one(client):
    single_resp = await client.post(
        "/api/hanger-calc",
        json={"items": [{"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800}]},
    )
    batch_resp = await client.post(
        "/api/hanger-calc",
        json={
            "items": [
                {"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800},
                {"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800},
            ]
        },
    )
    assert single_resp.status_code == 200
    assert batch_resp.status_code == 200
    single = single_resp.json()["results"][0]
    batch = batch_resp.json()["results"]
    # single = batch из одного элемента: результат совпадает с каждым элементом batch
    assert batch == [single, single]


@pytest.mark.asyncio
async def test_non_finite_item_fields_are_not_calculable(client):
    # NaN/Infinity не являются валидным JSON — шлём сырым телом. Движок
    # считает их нерасчётными данными (is_calculable=false), исключений нет.
    for bad in ["NaN", "Infinity", "-Infinity"]:
        resp = await client.post(
            "/api/hanger-calc",
            content=(
                '{"items":[{"perimeter_mm": ' + bad + ', "mount_width_mm": 19.35, "length_mm": 2800}]}'
            ),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200, f"expected 200 for perimeter_mm={bad!r}"
        (result,) = resp.json()["results"]
        assert result["is_calculable"] is False
        assert result["total"] is None


@pytest.mark.asyncio
async def test_non_finite_constants_are_rejected_with_422(client):
    for bad in ["NaN", "Infinity", "-Infinity"]:
        resp = await client.post(
            "/api/hanger-calc",
            content=(
                '{"items":[{"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800}],'
                '"hanger":{"area_limit_m2": ' + bad + "}}"
            ),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422, f"expected 422 for area_limit_m2={bad!r}"


@pytest.mark.asyncio
async def test_non_calculable_items_return_null_fields_without_exception(client):
    resp = await client.post(
        "/api/hanger-calc",
        json={
            "items": [
                {"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": None},
                {"perimeter_mm": None, "mount_width_mm": 19.35, "length_mm": 2800},
                {"perimeter_mm": 0, "mount_width_mm": 19.35, "length_mm": 2800},
            ]
        },
    )
    assert resp.status_code == 200
    for result in resp.json()["results"]:
        assert result == {
            "by_area": None,
            "by_size": None,
            "total": None,
            "limiter": None,
            "area_m2": None,
            "is_calculable": False,
        }


@pytest.mark.asyncio
async def test_invalid_constants_return_422(client):
    cases = [
        {"area_limit_m2": 0},
        {"area_limit_m2": -5},
        {"rod_length_mm": 0},
        {"gap_mm": -1},
        {"rod_count": 0},
    ]
    for hanger in cases:
        resp = await client.post(
            "/api/hanger-calc",
            json={
                "items": [{"perimeter_mm": 64.2, "mount_width_mm": 19.35, "length_mm": 2800}],
                "hanger": hanger,
            },
        )
        assert resp.status_code == 422, f"expected 422 for hanger={hanger}"


@pytest.mark.asyncio
async def test_cross_field_incompatibility_returns_422(client):
    resp = await client.post(
        "/api/hanger-calc",
        json={
            "items": [{"perimeter_mm": 64.2, "mount_width_mm": 2000, "length_mm": 2800}],
        },
    )
    assert resp.status_code == 422
    assert "Несовместимые данные" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_custom_hanger_settings_applied_and_echoed(client):
    resp = await client.post(
        "/api/hanger-calc",
        json={
            "items": [{"perimeter_mm": 100, "mount_width_mm": 100, "length_mm": 1000}],
            "hanger": {"area_limit_m2": 10, "rod_length_mm": 2000, "gap_mm": 0, "rod_count": 1},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    (result,) = body["results"]
    assert result["by_area"] == 100
    assert result["by_size"] == 20
    assert result["total"] == 20
    assert result["limiter"] == "size"
    assert body["hanger"] == {"area_limit_m2": 10.0, "rod_length_mm": 2000.0, "gap_mm": 0.0, "rod_count": 1}


@pytest.mark.asyncio
async def test_empty_items_returns_default_constants(client):
    resp = await client.post("/api/hanger-calc", json={"items": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["hanger"] == {"area_limit_m2": 13.0, "rod_length_mm": 1450.0, "gap_mm": 20.0, "rod_count": 2}
