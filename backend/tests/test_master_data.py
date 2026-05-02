import pytest
from sqlalchemy.exc import IntegrityError

from app.models.bom import BOM, BOMLine
from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section


@pytest.mark.asyncio
async def test_unique_sku(session) -> None:
    session.add(Product(sku="SKU-1", name="Product 1", type=ProductType.finished_good, unit="pcs"))
    await session.commit()

    session.add(Product(sku="SKU-1", name="Duplicate", type=ProductType.finished_good, unit="pcs"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_one_active_bom_per_product(session) -> None:
    product = Product(sku="SKU-BOM", name="With BOM", type=ProductType.finished_good, unit="pcs")
    component = Product(sku="CMP-1", name="Component", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    bom1 = BOM(product_id=product.id, version="v1", is_active=True)
    session.add(bom1)
    await session.flush()
    session.add(BOMLine(bom_id=bom1.id, component_product_id=component.id, quantity=1, unit="pcs"))
    await session.commit()

    session.add(BOM(product_id=product.id, version="v2", is_active=True))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_one_active_route_per_product(session) -> None:
    section = Section(code="SEC-1", name="Section 1")
    product = Product(sku="SKU-ROUTE", name="With Route", type=ProductType.finished_good, unit="pcs")
    session.add_all([section, product])
    await session.flush()

    route1 = ProductionRoute(product_id=product.id, name="Main", version="v1", is_active=True)
    session.add(route1)
    await session.flush()
    session.add(RouteStep(route_id=route1.id, sequence=1, section_id=section.id, operation_name="Op1", is_final=True))
    await session.commit()

    session.add(ProductionRoute(product_id=product.id, name="Main2", version="v2", is_active=True))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_route_step_sequence_uniqueness(session) -> None:
    section = Section(code="SEC-2", name="Section 2")
    product = Product(sku="SKU-SEQ", name="Seq Product", type=ProductType.finished_good, unit="pcs")
    session.add_all([section, product])
    await session.flush()

    route = ProductionRoute(product_id=product.id, name="Route", version="v1", is_active=True)
    session.add(route)
    await session.flush()

    session.add(RouteStep(route_id=route.id, sequence=1, section_id=section.id, operation_name="Op1", is_final=False))
    session.add(RouteStep(route_id=route.id, sequence=1, section_id=section.id, operation_name="Op2", is_final=True))
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
        json={"product_id": product.id, "name": "Route", "version": "v1", "is_active": True},
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
