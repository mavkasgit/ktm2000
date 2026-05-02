import pytest


@pytest.mark.asyncio
async def test_create_and_list_import_templates(client) -> None:
    response = await client.post(
        "/api/import-templates",
        json={"name": "Test Template", "column_mapping": {"A": "sku", "B": "quantity"}},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Test Template"
    assert created["column_mapping"] == {"A": "sku", "B": "quantity"}
    assert "id" in created

    list_response = await client.get("/api/import-templates")
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) >= 1
    assert any(item["id"] == created["id"] for item in items)
