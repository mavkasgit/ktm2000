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


@pytest.mark.asyncio
async def test_search_products_includes_is_paired_profile(client, session) -> None:
    # 1. Create a product with is_paired_profile=True
    prod1 = Product(sku="SKU-PAIR-Y", name="Paired Prod Y", type=ProductType.finished_good, unit="pcs", is_paired_profile=True)
    # 2. Create a product with is_paired_profile=False
    prod2 = Product(sku="SKU-PAIR-N", name="Non-paired Prod N", type=ProductType.finished_good, unit="pcs", is_paired_profile=False)
    session.add_all([prod1, prod2])
    await session.commit()

    # 3. Call search API
    resp = await client.get("/api/products/search/products", params={"q": "SKU-PAIR"})
    assert resp.status_code == 200
    data = resp.json()
    
    # 4. Verify fields
    item1 = next(item for item in data if item["sku"] == "SKU-PAIR-Y")
    item2 = next(item for item in data if item["sku"] == "SKU-PAIR-N")
    assert item1["is_paired_profile"] is True
    assert item2["is_paired_profile"] is False


@pytest.mark.asyncio
async def test_product_includes_techcard_flags(client, session) -> None:
    # 1. Create components and finished products
    comp1 = Product(sku="COMP-STDT", name="Component with standard techcard", type=ProductType.component, unit="pcs")
    comp2 = Product(sku="COMP-PAIRDT", name="Component with paired techcard", type=ProductType.component, unit="pcs")
    comp3 = Product(sku="COMP-NOTC", name="Component with no techcard", type=ProductType.component, unit="pcs")
    session.add_all([comp1, comp2, comp3])
    await session.commit()

    # 2. Create standard techcard directly for comp1
    tc_std = Techcard(product_id=comp1.id, version="v1", processing_type="standart_processing", is_active=True)
    # Create paired techcard and add comp2 to its lines
    tc_paired = Techcard(product_id=None, version="v1", processing_type="paired_processing", is_active=True)
    session.add_all([tc_std, tc_paired])
    await session.commit()

    line = TechcardLine(techcard_id=tc_paired.id, component_product_id=comp2.id, quantity=1, unit="pcs")
    session.add(line)
    await session.commit()

    # 3. Call list products API
    resp = await client.get("/api/products", params={"type": "component"})
    assert resp.status_code == 200
    data = resp.json()

    # Verify standard techcard flag
    item1 = next(item for item in data if item["id"] == comp1.id)
    assert item1["has_standard_techcard"] is True
    assert item1["has_paired_techcard"] is False

    # Verify paired techcard flag
    item2 = next(item for item in data if item["id"] == comp2.id)
    assert item2["has_standard_techcard"] is False
    assert item2["has_paired_techcard"] is True

    # Verify no techcard flags
    item3 = next(item for item in data if item["id"] == comp3.id)
    assert item3["has_standard_techcard"] is False
    assert item3["has_paired_techcard"] is False


@pytest.mark.asyncio
async def test_delete_product_cascade_techcards(client, session) -> None:
    # 1. Create a product with a standard techcard and a component
    prod = Product(sku="DEL-PROD", name="Product to delete", type=ProductType.finished_good, unit="pcs")
    comp = Product(sku="DEL-COMP", name="Component to delete", type=ProductType.component, unit="pcs")
    session.add_all([prod, comp])
    await session.commit()

    # Create a techcard for prod
    tc = Techcard(product_id=prod.id, version="v1", processing_type="standart_processing", is_active=True)
    session.add(tc)
    await session.commit()

    # Create a techcard line referencing comp
    line = TechcardLine(techcard_id=tc.id, component_product_id=comp.id, quantity=5.0, unit="pcs")
    session.add(line)
    await session.commit()

    # 2. Try to delete the product (should delete standard techcard cascade-wise)
    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 204

    # Verify that the techcard and the product are deleted
    assert (await session.get(Product, prod.id)) is None
    assert (await session.get(Techcard, tc.id)) is None
    assert (await session.get(TechcardLine, line.id)) is None

    # 3. Now try to delete the component (should delete any techcard referencing it)
    prod2 = Product(sku="DEL-PROD2", name="Another product", type=ProductType.finished_good, unit="pcs")
    session.add(prod2)
    await session.commit()

    tc2 = Techcard(product_id=prod2.id, version="v1", processing_type="standart_processing", is_active=True)
    session.add(tc2)
    await session.commit()

    line2 = TechcardLine(techcard_id=tc2.id, component_product_id=comp.id, quantity=3.0, unit="pcs")
    session.add(line2)
    await session.commit()

    # Delete comp -> should delete tc2 and line2 cascade-wise
    resp = await client.delete(f"/api/products/{comp.id}")
    assert resp.status_code == 204

    # Verify that comp, tc2, line2 are deleted
    assert (await session.get(Product, comp.id)) is None
    assert (await session.get(Techcard, tc2.id)) is None
    assert (await session.get(TechcardLine, line2.id)) is None


@pytest.mark.asyncio
async def test_delete_product_blockers_and_spg_remainder_cascade(client, session) -> None:
    from app.models.defect import Defect
    from app.models.movement import Movement
    from app.models.transfer import Transfer
    from app.models.rework_task import ReworkTask
    from app.models.spg_remainder import SpgRemainder
    from app.models.work_task import WorkTask
    from app.models.section import Section
    from app.models.spg import StorageProductionGroup
    from app.models.production_plan import ProductionPlan, PlanPosition, PlanSourceType, PlanPositionStatus, PlanPositionValidationStatus

    # Setup basic product
    prod = Product(sku="TEST-BLOCKER-PROD", name="Test Blocker Product", type=ProductType.finished_good, unit="pcs")
    other_prod = Product(sku="OTHER-PROD", name="Other Product", type=ProductType.finished_good, unit="pcs")
    session.add_all([prod, other_prod])
    await session.commit()

    # Setup Section & SPG (needed for some models)
    sec = Section(name="Test Section", code="TS")
    spg = StorageProductionGroup(name="Test SPG", code="TSPG")
    session.add_all([sec, spg])
    await session.commit()

    # 1. Test SpgRemainder cascade deletion
    rem = SpgRemainder(product_id=prod.id, spg_id=spg.id, original_issued=10.0, remainder_quantity=0.0)
    session.add(rem)
    await session.commit()

    # Deleting should succeed because SpgRemainder is cascade deleted
    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 204
    assert (await session.get(Product, prod.id)) is None
    assert (await session.get(SpgRemainder, rem.id)) is None

    # Re-create product for blocker tests
    prod = Product(sku="TEST-BLOCKER-PROD", name="Test Blocker Product", type=ProductType.finished_good, unit="pcs")
    session.add(prod)
    await session.commit()

    # 2. Test Defect blocker
    defect = Defect(product_id=prod.id, section_id=sec.id, created_by=1)
    session.add(defect)
    await session.commit()

    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 409
    assert "дефекты" in resp.json()["detail"]

    # Clean up defect
    await session.delete(defect)
    await session.commit()

    # 3. Test Movement blocker
    move = Movement(product_id=prod.id, movement_type="adjustment", quantity=5.0, created_by=1)
    session.add(move)
    await session.commit()

    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 409
    assert "движения по складу" in resp.json()["detail"]

    # Clean up movement
    await session.delete(move)
    await session.commit()

    # 4. Test Transfer blocker
    # Needs two WorkTasks for another product (other_prod)
    from app.models.route import ProductionRoute, RouteStage
    from app.models.internal_plan import InternalPlan, SectionPlanLine
    from app.models.work_task import WorkTask, WorkTaskStatus

    # Create Route
    route = ProductionRoute(name="Test Route for Blocker")
    session.add(route)
    await session.flush()

    stage = RouteStage(route_id=route.id, sequence=1, section_id=sec.id)
    session.add(stage)
    await session.flush()

    plan = ProductionPlan(plan_no="PL-TEST-1", name="Test Plan")
    session.add(plan)
    await session.flush()

    pp1 = PlanPosition(
        production_plan_id=plan.id,
        product_id=other_prod.id,
        source_type=PlanSourceType.manual,
        source_sku=other_prod.sku,
        quantity=10.0,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
    )
    pp2 = PlanPosition(
        production_plan_id=plan.id,
        product_id=other_prod.id,
        source_type=PlanSourceType.manual,
        source_sku=other_prod.sku,
        quantity=10.0,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
    )
    session.add_all([pp1, pp2])
    await session.flush()

    # Create InternalPlan
    int_plan = InternalPlan(production_plan_id=plan.id)
    session.add(int_plan)
    await session.flush()

    # Create SectionPlanLines
    spl1 = SectionPlanLine(
        internal_plan_id=int_plan.id,
        plan_position_id=pp1.id,
        section_id=sec.id,
        product_id=other_prod.id,
        route_id=route.id,
        route_stage_id=stage.id,
        sequence=1,
        planned_quantity=10.0,
    )
    spl2 = SectionPlanLine(
        internal_plan_id=int_plan.id,
        plan_position_id=pp2.id,
        section_id=sec.id,
        product_id=other_prod.id,
        route_id=route.id,
        route_stage_id=stage.id,
        sequence=1,
        planned_quantity=10.0,
    )
    session.add_all([spl1, spl2])
    await session.flush()

    wt1 = WorkTask(
        section_plan_line_id=spl1.id,
        section_id=sec.id,
        product_id=other_prod.id,
        route_stage_id=stage.id,
        planned_quantity=10.0,
        status=WorkTaskStatus.ready,
    )
    wt2 = WorkTask(
        section_plan_line_id=spl2.id,
        section_id=sec.id,
        product_id=other_prod.id,
        route_stage_id=stage.id,
        planned_quantity=10.0,
        status=WorkTaskStatus.ready,
    )
    session.add_all([wt1, wt2])
    await session.commit()

    transfer = Transfer(
        transfer_no="TR-TEST-1",
        from_task_id=wt1.id,
        to_task_id=wt2.id,
        from_section_id=sec.id,
        to_section_id=sec.id,
        product_id=prod.id,
        sent_quantity=5.0
    )
    session.add(transfer)
    await session.commit()

    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 409
    assert "передачи" in resp.json()["detail"]

    # Clean up transfer
    await session.delete(transfer)
    await session.commit()

    # 5. Test ReworkTask blocker
    # We need a defect and a task for ReworkTask
    wt3 = WorkTask(
        section_plan_line_id=spl1.id,
        section_id=sec.id,
        product_id=other_prod.id,
        route_stage_id=stage.id,
        planned_quantity=10.0,
        status=WorkTaskStatus.ready,
    )
    session.add(wt3)
    await session.commit()

    defect2 = Defect(product_id=other_prod.id, section_id=sec.id, created_by=1)
    session.add(defect2)
    await session.commit()

    rework = ReworkTask(
        defect_id=defect2.id,
        source_task_id=wt3.id,
        section_id=sec.id,
        product_id=prod.id,
        quantity=5.0,
        created_by=1
    )
    session.add(rework)
    await session.commit()

    resp = await client.delete(f"/api/products/{prod.id}")
    assert resp.status_code == 409
    assert "задачи доработки" in resp.json()["detail"]




