import pytest


@pytest.mark.asyncio
async def test_create_and_update_profile_with_excel_passport(client) -> None:
    create_response = await client.post(
        "/api/route-rule-profiles",
        json={
            "code": "passport-profile",
            "name": "Профиль с паспортом",
            "is_active": True,
            "priority": 10,
            "excel_column_passport": [
                {"index": 8, "letter": "H", "header": "Пробивка/сверловка", "field_path": "operation"},
                {"index": 15, "letter": "O", "header": "Вид конечного продукта", "field_path": "output_kind"},
            ],
            "excel_passport_meta": {"sheet_name": "Май", "sheet_index": 0, "source_row_number": 12},
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["code"] == "passport-profile"
    assert len(created["excel_column_passport"]) == 2
    assert created["excel_column_passport"][0]["index"] == 8
    assert created["excel_passport_meta"]["sheet_name"] == "Май"

    update_response = await client.put(
        f"/api/route-rule-profiles/{created['id']}",
        json={
            "code": "passport-profile",
            "name": "Профиль с паспортом v2",
            "is_active": True,
            "priority": 20,
            "excel_column_passport": [
                {"index": 20, "letter": "T", "header": "Клиент", "field_path": "customer"},
            ],
            "excel_passport_meta": {"sheet_name": "Июнь", "sheet_index": 1, "source_row_number": 22},
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["name"] == "Профиль с паспортом v2"
    assert updated["excel_column_passport"] == [
        {"index": 20, "letter": "T", "header": "Клиент", "field_path": "customer"}
    ]
    assert updated["excel_passport_meta"]["source_row_number"] == 22


@pytest.mark.asyncio
async def test_profile_rejects_duplicate_passport_indexes(client) -> None:
    response = await client.post(
        "/api/route-rule-profiles",
        json={
            "code": "invalid-passport-profile",
            "name": "Невалидный паспорт",
            "is_active": True,
            "priority": 0,
            "excel_column_passport": [
                {"index": 8, "letter": "H", "header": "Пробивка/сверловка", "field_path": "operation"},
                {"index": 8, "letter": "H", "header": "Пробивка/сверловка", "field_path": "operation_duplicate"},
            ],
            "excel_passport_meta": {},
        },
    )
    assert response.status_code == 400
    assert "duplicate index" in response.json()["detail"]

