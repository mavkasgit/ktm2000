import pytest
from sqlalchemy.exc import IntegrityError

from app.models.techcard import Techcard, TechcardLine
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import StorageProductionGroup


@pytest.mark.asyncio
async def test_unique_sku(session) -> None:
    session.add(Product(sku="SKU-1", name="Product 1", type=ProductType.finished_good, unit="pcs"))
    await session.commit()

    session.add(Product(sku="SKU-1", name="Duplicate", type=ProductType.finished_good, unit="pcs"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_one_active_techcard_per_product(session) -> None:
    product = Product(sku="SKU-TECHCARD", name="With Techcard", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="CMP-1", name="Component", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    techcard1 = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard1)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard1.id, component_product_id=component.id, quantity=1, unit="pcs"))
    await session.commit()

    session.add(Techcard(product_id=product.id, version="v2", is_active=True))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_route_step_sequence_uniqueness(session) -> None:
    section = Section(code="SEC-2", name="Section 2")
    product = Product(sku="SKU-SEQ", name="Seq Product", type=ProductType.finished_good, unit="pcs")
    session.add_all([section, product])
    await session.flush()

    route = ProductionRoute(name="Route", is_active=True)
    session.add(route)
    await session.flush()

    stage1 = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=False)
    session.add(stage1)
    await session.flush()
    op1 = RouteOperation(route_stage_id=stage1.id, sequence=1, operation_name="Op1")
    session.add(op1)

    stage2 = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=True)
    session.add(stage2)
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_inactive_section_rejected_in_route_step(client, session) -> None:
    inactive = Section(code="SEC-INACTIVE", name="Inactive", is_active=False)
    product = Product(sku="SKU-API", name="API Product", type=ProductType.finished_good, unit="pcs")
    session.add_all([inactive, product])
    await session.commit()

    create_route = await client.post(
        "/api/routes",
        json={"name": "Route", "is_active": True},
    )
    assert create_route.status_code == 201
    route_id = create_route.json()["id"]

    add_step = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": inactive.id,
            "operation_name": "Should fail",
            "is_final": True,
        },
    )
    assert add_step.status_code == 400
    assert "inactive section" in add_step.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_section_with_sort_order(client, session) -> None:
    spg = StorageProductionGroup(code="SPG-SORT", name="SPG Sort")
    session.add(spg)
    await session.commit()

    payload = {"code": "TEST-SORT", "name": "Test Sort", "sort_order": 99, "spg_id": spg.id}
    resp = await client.post("/api/sections", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["sort_order"] == 99


@pytest.mark.asyncio
async def test_get_section_by_id(client, session) -> None:
    spg = StorageProductionGroup(code="SPG-GETME", name="SPG Get Me")
    session.add(spg)
    await session.commit()

    create_resp = await client.post(
        "/api/sections",
        json={"code": "GETME", "name": "Get Me", "sort_order": 5, "spg_id": spg.id},
    )
    section_id = create_resp.json()["id"]

    resp = await client.get(f"/api/sections/{section_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "GETME"
    assert data["sort_order"] == 5


@pytest.mark.asyncio
async def test_get_section_not_found(client) -> None:
    resp = await client.get("/api/sections/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_sections_ordered_by_sort_order(client, session) -> None:
    # Create sections with different sort_order values
    session.add(Section(code="Z-LAST", name="Z Last", sort_order=30))
    session.add(Section(code="A-FIRST", name="A First", sort_order=10))
    session.add(Section(code="M-MIDDLE", name="M Middle", sort_order=20))
    await session.commit()

    resp = await client.get("/api/sections")
    assert resp.status_code == 200
    data = resp.json()
    
    # Filter out seeded sections from other tests
    test_sections = [s for s in data if s["code"] in ("Z-LAST", "A-FIRST", "M-MIDDLE")]
    codes = [s["code"] for s in test_sections]
    assert codes == ["A-FIRST", "M-MIDDLE", "Z-LAST"]


@pytest.mark.asyncio
async def test_create_patch_section_with_spg(client, session) -> None:
    # 1. Create StorageProductionGroups
    spg1 = StorageProductionGroup(code="SPG1", name="SPG One")
    spg2 = StorageProductionGroup(code="SPG2", name="SPG Two")
    session.add_all([spg1, spg2])
    await session.commit()

    # 2. Create Section with SPG1
    payload = {
        "code": "SEC-SPG",
        "name": "Sec with SPG",
        "spg_id": spg1.id
    }
    resp = await client.post("/api/sections", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["spg_links"]) == 1
    assert data["spg_links"][0]["id"] == spg1.id
    section_id = data["id"]

    # 3. Patch Section to SPG2
    patch_payload = {
        "spg_id": spg2.id
    }
    resp = await client.patch(f"/api/sections/{section_id}", json=patch_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["spg_links"]) == 1
    assert data["spg_links"][0]["id"] == spg2.id

    # 4. Try to create with invalid SPG ID
    invalid_payload = {
        "code": "SEC-INVALID-SPG",
        "name": "Sec Invalid SPG",
        "spg_id": 99999
    }
    resp = await client.post("/api/sections", json=invalid_payload)
    assert resp.status_code == 400
    assert "spg id does not exist" in resp.json()["detail"].lower()

