import pytest
from sqlalchemy.exc import IntegrityError

from app.models.product import Product, ProductPair, ProductType
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

    resp = await client.get("/api/sections?limit=500&offset=0")
    assert resp.status_code == 200
    data = resp.json()["items"]
    
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


@pytest.mark.asyncio
async def test_search_products_includes_is_paired_profile(client, session) -> None:
    # 1. Create a pair — флаг выведенный (ADR-0023, #146): есть пара → True.
    prod1 = Product(sku="SKU-PAIR-Y", name="Paired Prod Y", type=ProductType.finished_good, unit="pcs")
    prod2 = Product(sku="SKU-PAIR-P", name="Paired Partner", type=ProductType.finished_good, unit="pcs")
    prod3 = Product(sku="SKU-PAIR-N", name="Non-paired Prod N", type=ProductType.finished_good, unit="pcs")
    session.add_all([prod1, prod2, prod3])
    await session.flush()
    session.add(ProductPair(product_a_id=min(prod1.id, prod2.id), product_b_id=max(prod1.id, prod2.id)))
    await session.commit()

    # 2. Call search API
    resp = await client.get("/api/products/search/products", params={"q": "SKU-PAIR"})
    assert resp.status_code == 200
    data = resp.json()

    # 3. Verify fields
    item1 = next(item for item in data if item["sku"] == "SKU-PAIR-Y")
    item2 = next(item for item in data if item["sku"] == "SKU-PAIR-N")
    assert item1["is_paired_profile"] is True
    assert item2["is_paired_profile"] is False


@pytest.mark.asyncio
async def test_patch_product_sku(client, session) -> None:
    """PATCH /products/{id} позволяет переименовать артикул."""
    product = Product(
        sku="OLD-SKU-001",
        name="Сырьё для переименования",
        type=ProductType.component,
        unit="pcs",
    )
    alias_holder = Product(
        sku="ALIAS-HOLDER",
        name="Держатель алиаса",
        type=ProductType.component,
        unit="pcs",
        aliases=["OLD-SKU-001"],
    )
    session.add_all([product, alias_holder])
    await session.commit()

    resp = await client.patch(
        f"/api/products/{product.id}",
        json={"sku": "NEW-SKU-001"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sku"] == "NEW-SKU-001"

    await session.refresh(alias_holder)
    assert alias_holder.aliases == ["NEW-SKU-001"]


