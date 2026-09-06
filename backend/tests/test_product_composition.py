"""Состав ГП на Product — модель и API (тикет #147).

Нормативная связь «компонент (сырьё type=component) + количество», 1–2
компонента на продукт. Чтение — роли раздела /references (admin, planner,
section_manager, operator); запись — REFERENCES_WRITER_ROLES
(= фронтовый POLICIES.editReferences). Лимит «не более 2» на уровне БД
держит триггер (зеркало миграции 053 в conftest), валидация — на API.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.main import app
from app.models.product import Product, ProductType
from app.models.user import User, UserRole


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str = "Test Product",
    type: ProductType = ProductType.component,
    unit: str = "pcs",
) -> Product:
    product = Product(sku=sku, name=name, type=type, unit=unit, is_active=True, aliases=[])
    session.add(product)
    await session.flush()
    return product


def _composition_payload(*items: dict) -> dict:
    return {"items": list(items)}


async def _force_role(session: AsyncSession, role: UserRole) -> None:
    """Подменить текущего пользователя (dev-bypass) на роль для 403-тестов."""
    user = User(username=f"composition_{role.value}", full_name=role.value, role=role, is_active=True)
    session.add(user)
    await session.flush()
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_composition_empty_by_default(client, session: AsyncSession) -> None:
    product = await _make_product(session, sku="CMP-OWNER-1", type=ProductType.finished_good)
    await session.commit()

    response = await client.get(f"/api/products/{product.id}/composition")
    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.asyncio
async def test_composition_put_then_get_roundtrip(client, session: AsyncSession) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-2", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A", name="Профиль А", unit="m")
    comp_b = await _make_product(session, sku="CMP-RAW-B", name="Профиль Б", unit="pcs")
    await session.commit()

    response = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload(
            {"component_product_id": comp_a.id, "quantity": 2.5},
            {"component_product_id": comp_b.id, "quantity": 1, "unit": "kg"},
        ),
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    by_sku = {i["sku"]: i for i in items}
    # unit по умолчанию — единица компонента; явный unit сохраняется как есть.
    assert by_sku["CMP-RAW-A"] == {
        "component_product_id": comp_a.id,
        "sku": "CMP-RAW-A",
        "name": "Профиль А",
        "is_active": True,
        "quantity": 2.5,
        "unit": "m",
    }
    assert by_sku["CMP-RAW-B"]["unit"] == "kg"

    fetched = await client.get(f"/api/products/{owner.id}/composition")
    assert fetched.status_code == 200
    assert fetched.json() == response.json()


@pytest.mark.asyncio
async def test_composition_replace_swaps_items_wholesale(client, session: AsyncSession) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-3", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A3")
    comp_b = await _make_product(session, sku="CMP-RAW-B3")
    await session.commit()

    first = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": comp_a.id, "quantity": 1}),
    )
    assert first.status_code == 200

    second = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": comp_b.id, "quantity": 4}),
    )
    assert second.status_code == 200
    skus = [i["sku"] for i in second.json()["items"]]
    assert skus == ["CMP-RAW-B3"]


@pytest.mark.asyncio
async def test_composition_clear_with_empty_items(client, session: AsyncSession) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-4", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A4")
    await session.commit()

    put = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": comp_a.id, "quantity": 1}),
    )
    assert put.status_code == 200

    cleared = await client.put(f"/api/products/{owner.id}/composition", json=_composition_payload())
    assert cleared.status_code == 200
    assert cleared.json() == {"items": []}


@pytest.mark.asyncio
async def test_composition_rejects_three_components(client, session: AsyncSession) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-5", type=ProductType.finished_good)
    raws = [await _make_product(session, sku=f"CMP-RAW-5-{i}") for i in range(3)]
    await session.commit()

    response = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload(*[
            {"component_product_id": raw.id, "quantity": 1} for raw in raws
        ]),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_composition_db_trigger_backstops_max_two(client, session: AsyncSession) -> None:
    """Бэкстоп БД: третья строка владельца отклоняется даже мимо API."""
    owner = await _make_product(session, sku="CMP-OWNER-6", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-6-0")
    comp_b = await _make_product(session, sku="CMP-RAW-6-1")
    comp_c = await _make_product(session, sku="CMP-RAW-6-2")
    await session.commit()

    put = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload(
            {"component_product_id": comp_a.id, "quantity": 1},
            {"component_product_id": comp_b.id, "quantity": 1},
        ),
    )
    assert put.status_code == 200

    with pytest.raises(Exception) as exc_info:
        await session.execute(text(
            "INSERT INTO product_compositions (product_id, component_product_id, quantity) "
            "VALUES (:pid, :cid, 1)"
        ), {"pid": owner.id, "cid": comp_c.id})
    assert "at most 2 components" in str(exc_info.value)
    await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_maker, detail_part",
    [
        # quantity <= 0
        (lambda comp_id: {"items": [{"component_product_id": comp_id, "quantity": 0}]}, None),
        (lambda comp_id: {"items": [{"component_product_id": comp_id, "quantity": -1}]}, None),
        # несуществующий компонент
        (lambda comp_id: {"items": [{"component_product_id": 999999, "quantity": 1}]}, "not found"),
        # самоссылка
        (lambda comp_id: {"items": [{"component_product_id": comp_id, "quantity": 1}]}, "own component"),
        # дубликат компонента
        (
            lambda comp_id: {
                "items": [
                    {"component_product_id": comp_id, "quantity": 1},
                    {"component_product_id": comp_id, "quantity": 2},
                ]
            },
            "Duplicate",
        ),
    ],
)
async def test_composition_validation_errors(client, session, payload_maker, detail_part) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-7", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A7")
    await session.commit()

    payload = payload_maker(owner.id if "own" in (detail_part or "") else comp_a.id)
    response = await client.put(f"/api/products/{owner.id}/composition", json=payload)
    assert response.status_code == 422
    if detail_part:
        assert detail_part in response.json()["detail"]


@pytest.mark.asyncio
async def test_composition_rejects_non_component_type(client, session: AsyncSession) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-8", type=ProductType.finished_good)
    finished = await _make_product(session, sku="CMP-FG-8", type=ProductType.finished_good)
    await session.commit()

    response = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": finished.id, "quantity": 1}),
    )
    assert response.status_code == 422
    assert "type=component" in response.json()["detail"]


@pytest.mark.asyncio
async def test_composition_404_for_unknown_product(client) -> None:
    assert (await client.get("/api/products/999999/composition")).status_code == 404
    assert (
        await client.put("/api/products/999999/composition", json=_composition_payload())
    ).status_code == 404


@pytest.mark.asyncio
async def test_composition_read_roles(client, session: AsyncSession) -> None:
    """Чтение — как у «Сырья»: operator пускают, viewer/transporter — нет."""
    product = await _make_product(session, sku="CMP-OWNER-9", type=ProductType.finished_good)
    await session.commit()

    for role, expected_status in [
        (UserRole.operator, 200),
        (UserRole.viewer, 403),
        (UserRole.transporter, 403),
    ]:
        await _force_role(session, role)
        response = await client.get(f"/api/products/{product.id}/composition")
        assert response.status_code == expected_status, f"{role.value}: {response.status_code}"
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_composition_write_requires_edit_references(client, session: AsyncSession) -> None:
    """Запись — POLICIES.editReferences: operator — 403, planner — пишет."""
    owner = await _make_product(session, sku="CMP-OWNER-10", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A10")
    await session.commit()

    payload = _composition_payload({"component_product_id": comp_a.id, "quantity": 1})

    await _force_role(session, UserRole.operator)
    forbidden = await client.put(f"/api/products/{owner.id}/composition", json=payload)
    assert forbidden.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)

    await _force_role(session, UserRole.planner)
    allowed = await client.put(f"/api/products/{owner.id}/composition", json=payload)
    assert allowed.status_code == 200
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_delete_product_blocked_while_component_in_composition(client, session) -> None:
    """Сырьё, входящее в состав, нельзя удалить, пока состав не разобран."""
    owner = await _make_product(session, sku="CMP-OWNER-11", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A11")
    await session.commit()

    put = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": comp_a.id, "quantity": 2}),
    )
    assert put.status_code == 200

    blocked = await client.delete(f"/api/products/{comp_a.id}")
    assert blocked.status_code == 409
    assert "состав ГП" in blocked.json()["detail"]

    # Разобрали состав → сырьё удаляется; состав владельца уходит вместе с ним.
    cleared = await client.put(f"/api/products/{owner.id}/composition", json=_composition_payload())
    assert cleared.status_code == 200
    assert (await client.delete(f"/api/products/{comp_a.id}")).status_code == 204


@pytest.mark.asyncio
async def test_delete_owner_cascades_composition(client, session) -> None:
    owner = await _make_product(session, sku="CMP-OWNER-12", type=ProductType.finished_good)
    comp_a = await _make_product(session, sku="CMP-RAW-A12")
    await session.commit()

    put = await client.put(
        f"/api/products/{owner.id}/composition",
        json=_composition_payload({"component_product_id": comp_a.id, "quantity": 2}),
    )
    assert put.status_code == 200

    assert (await client.delete(f"/api/products/{owner.id}")).status_code == 204
    remaining = await session.execute(text("SELECT count(*) FROM product_compositions"))
    assert remaining.scalar() == 0
