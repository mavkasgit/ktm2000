import pytest

ALL_SECTIONS = [
    "/",
    "/references",
    "/planning",
    "/execution",
    "/section-tasks",
    "/transfers",
    "/spg",
    "/audit-logs",
    "/settings",
    "/settings/dev",
    "/dev",
]

EXPECTED_ROLES = {
    "admin": {
        "label": "Администратор",
        "sections": ALL_SECTIONS,
    },
    "planner": {
        "label": "Планировщик",
        "sections": [s for s in ALL_SECTIONS if s != "/settings/dev"],
    },
    "section_manager": {
        "label": "Начальник участка",
        "sections": [s for s in ALL_SECTIONS if s not in ("/planning", "/settings/dev")],
    },
    "operator": {
        "label": "Оператор",
        "sections": [s for s in ALL_SECTIONS if s not in ("/planning", "/execution", "/settings/dev")],
    },
    "viewer": {
        "label": "Наблюдатель",
        "sections": [
            s for s in ALL_SECTIONS if s not in ("/planning", "/execution", "/transfers", "/settings/dev")
        ],
    },
    "transporter": {
        "label": "Транспортировщик",
        "sections": [s for s in ALL_SECTIONS if s not in ("/planning", "/execution", "/settings/dev")],
    },
}


@pytest.mark.asyncio
async def test_auth_roles_returns_all_six_roles(client) -> None:
    response = await client.get("/api/auth/roles")

    assert response.status_code == 200
    roles = response.json()["roles"]
    assert len(roles) == 6
    assert {r["code"] for r in roles} == set(EXPECTED_ROLES)


@pytest.mark.asyncio
async def test_auth_roles_matches_contract(client) -> None:
    """Справочник совпадает с Контрактом спеки #14: коды, подписи и секции."""
    response = await client.get("/api/auth/roles")

    assert response.status_code == 200
    by_code = {r["code"]: r for r in response.json()["roles"]}
    assert set(by_code) == set(EXPECTED_ROLES)
    for code, expected in EXPECTED_ROLES.items():
        assert by_code[code]["label"] == expected["label"], f"label mismatch for {code}"
        assert by_code[code]["sections"] == expected["sections"], f"sections mismatch for {code}"


@pytest.mark.asyncio
async def test_auth_roles_admin_has_all_sections(client) -> None:
    response = await client.get("/api/auth/roles")

    assert response.status_code == 200
    admin = next(r for r in response.json()["roles"] if r["code"] == "admin")
    assert admin["label"] == "Администратор"
    assert admin["sections"] == ALL_SECTIONS


@pytest.mark.asyncio
async def test_auth_roles_viewer_has_no_transfers(client) -> None:
    response = await client.get("/api/auth/roles")

    assert response.status_code == 200
    viewer = next(r for r in response.json()["roles"] if r["code"] == "viewer")
    assert viewer["label"] == "Наблюдатель"
    assert "/transfers" not in viewer["sections"]


@pytest.mark.asyncio
async def test_auth_roles_operator_label_and_sections(client) -> None:
    response = await client.get("/api/auth/roles")

    assert response.status_code == 200
    operator = next(r for r in response.json()["roles"] if r["code"] == "operator")
    assert operator["label"] == "Оператор"
    assert "/transfers" in operator["sections"]
    assert "/planning" not in operator["sections"]
    assert "/execution" not in operator["sections"]
