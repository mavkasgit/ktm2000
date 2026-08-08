"""Server-side column filters and sort for GET /api/products."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductLength, ProcessingFlag, ProductProcessingFlag, ProductType

# Курируемый набор полей сортировки справочника сырья (#76)
CURATED_SORT_FIELDS = [
    "sku", "code", "name", "type", "unit", "is_active", "is_catalog_item",
    "is_paired_profile", "profile_type", "alloy", "color", "anod_type",
    "source", "dimension_state", "id",
    "length_mm", "weight_per_meter", "perimeter_mm", "mount_width_mm", "cross_section",
    "quantity_per_hanger", "aliases", "skip_shot_blast", "is_laminated",
]


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str,
    lengths_mm: list[float] | None = None,
    is_paired_profile: bool = False,
    aliases: list[str] | None = None,
    attributes: dict | None = None,
) -> Product:
    product = Product(
        sku=sku,
        name=name,
        type=ProductType.component,
        unit="pcs",
        is_active=True,
        is_paired_profile=is_paired_profile,
        aliases=aliases or [],
        attributes=attributes or {},
    )
    session.add(product)
    await session.flush()
    for length_mm in lengths_mm or []:
        session.add(ProductLength(product_id=product.id, length_mm=length_mm))
    await session.flush()
    return product


async def _add_processing_flag(session: AsyncSession, product: Product, code: str) -> None:
    flag = ProcessingFlag(code=code, name=code)
    session.add(flag)
    await session.flush()
    session.add(ProductProcessingFlag(product_id=product.id, flag_id=flag.id))
    await session.flush()


@pytest.mark.asyncio
async def test_products_filter_sku_param(client, session: AsyncSession) -> None:
    target = await _make_product(session, sku="RM-UNIQUE-777", name="Target Product")
    for i in range(55):
        await _make_product(session, sku=f"RM-AAA-{i:03d}", name=f"Page filler {i}")
    await session.commit()

    first_page = await client.get("/api/products?limit=50&offset=0")
    assert first_page.status_code == 200
    first_page_body = first_page.json()
    first_page_skus = {item["sku"] for item in first_page_body["items"]}
    assert target.sku not in first_page_skus

    filtered = await client.get("/api/products?sku=UNIQUE-777&limit=50&offset=0")
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["sku"] == "RM-UNIQUE-777"
    assert filtered.headers["x-total-count"] == "1"


@pytest.mark.asyncio
async def test_products_sort_name_asc(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-SORT-Z", name="Zulu Profile")
    await _make_product(session, sku="RM-SORT-A", name="Alpha Profile")
    await _make_product(session, sku="RM-SORT-M", name="Mike Profile")
    await session.commit()

    response = await client.get("/api/products?sort=name:asc&limit=50")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"] if item["sku"].startswith("RM-SORT-")]
    assert names == ["Alpha Profile", "Mike Profile", "Zulu Profile"]


@pytest.mark.asyncio
async def test_products_sort_curated_fields_accepted(client, session: AsyncSession) -> None:
    """Каждое поле курируемого набора (#76) принимается в asc и desc без 400."""
    await _make_product(session, sku="RM-CUR-1", name="Curated One")
    await session.commit()

    for field in CURATED_SORT_FIELDS:
        for order in ("asc", "desc"):
            response = await client.get(f"/api/products?sort={field}:{order}&limit=50")
            assert response.status_code == 200, f"{field}:{order} -> {response.status_code} {response.text}"


@pytest.mark.asyncio
async def test_products_sort_paired_profile_desc(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-PAIR-A", name="Paired A", is_paired_profile=True)
    await _make_product(session, sku="RM-PAIR-B", name="Plain B")
    await _make_product(session, sku="RM-PAIR-C", name="Plain C")
    await session.commit()

    response = await client.get("/api/products?sort=is_paired_profile:desc&limit=50")
    assert response.status_code == 200, response.text
    skus = [item["sku"] for item in response.json()["items"] if item["sku"].startswith("RM-PAIR-")]
    assert set(skus) == {"RM-PAIR-A", "RM-PAIR-B", "RM-PAIR-C"}
    assert skus[0] == "RM-PAIR-A"


@pytest.mark.asyncio
async def test_products_sort_processing_flags_boolean(client, session: AsyncSession) -> None:
    shot = await _make_product(session, sku="RM-FLAG-S", name="Skip Shot")
    laminated = await _make_product(session, sku="RM-FLAG-L", name="Laminated")
    await _make_product(session, sku="RM-FLAG-N", name="No Flags")
    await _add_processing_flag(session, shot, "skip_shot_blast")
    await _add_processing_flag(session, laminated, "is_laminated")
    await session.commit()

    resp_shot_desc = await client.get("/api/products?sort=skip_shot_blast:desc&limit=50")
    assert resp_shot_desc.status_code == 200, resp_shot_desc.text
    skus_shot = [item["sku"] for item in resp_shot_desc.json()["items"] if item["sku"].startswith("RM-FLAG-")]
    assert set(skus_shot) == {"RM-FLAG-S", "RM-FLAG-L", "RM-FLAG-N"}
    assert skus_shot[0] == "RM-FLAG-S"

    resp_shot_asc = await client.get("/api/products?sort=skip_shot_blast:asc&limit=50")
    assert resp_shot_asc.status_code == 200, resp_shot_asc.text
    skus_shot_asc = [item["sku"] for item in resp_shot_asc.json()["items"] if item["sku"].startswith("RM-FLAG-")]
    assert skus_shot_asc[-1] == "RM-FLAG-S"

    resp_lam = await client.get("/api/products?sort=is_laminated:desc&limit=50")
    assert resp_lam.status_code == 200, resp_lam.text
    skus_lam = [item["sku"] for item in resp_lam.json()["items"] if item["sku"].startswith("RM-FLAG-")]
    assert skus_lam[0] == "RM-FLAG-L"


@pytest.mark.asyncio
async def test_products_sort_aliases_by_joined_text(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-ALPHA", name="Alpha", aliases=["zeta", "alpha"])
    await _make_product(session, sku="RM-BETA", name="Beta", aliases=["mid"])
    await _make_product(session, sku="RM-EMPTY", name="Empty")
    await session.commit()

    response = await client.get("/api/products?sort=aliases:asc&limit=50")
    assert response.status_code == 200, response.text
    skus = [item["sku"] for item in response.json()["items"] if item["sku"].startswith("RM-")]
    # array_to_string: "" < "mid" < "zeta,alpha"
    assert skus == ["RM-EMPTY", "RM-BETA", "RM-ALPHA"]


@pytest.mark.asyncio
async def test_products_sort_jsonb_numeric_and_text(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-W2", name="W2", attributes={"weight_per_meter": 2.5})
    await _make_product(session, sku="RM-W0", name="W0", attributes={"weight_per_meter": 0.5})
    await _make_product(session, sku="RM-W1", name="W1", attributes={"weight_per_meter": 1.0})
    await _make_product(session, sku="RM-C1", name="C1", attributes={"cross_section": "B"})
    await _make_product(session, sku="RM-C2", name="C2", attributes={"cross_section": "A"})
    await _make_product(session, sku="RM-C3", name="C3")
    await session.commit()

    resp_num = await client.get("/api/products?sort=weight_per_meter:asc&limit=50")
    assert resp_num.status_code == 200, resp_num.text
    skus_num = [item["sku"] for item in resp_num.json()["items"] if item["sku"].startswith("RM-W")]
    assert skus_num == ["RM-W0", "RM-W1", "RM-W2"]

    resp_text = await client.get("/api/products?sort=cross_section:asc&limit=50")
    assert resp_text.status_code == 200, resp_text.text
    skus_text = [item["sku"] for item in resp_text.json()["items"] if item["sku"].startswith("RM-C")]
    # NULL (нет ключа) сортируется последним при ASC
    assert skus_text == ["RM-C2", "RM-C1", "RM-C3"]


@pytest.mark.asyncio
async def test_products_sort_invalid_field_400(client, session: AsyncSession) -> None:
    await _make_product(session, sku="RM-ERR-1", name="Err")
    await session.commit()

    response = await client.get("/api/products?sort=unkown:asc&limit=50")
    assert response.status_code == 400

    response2 = await client.get("/api/products?sort=sku:sideways&limit=50")
    assert response2.status_code == 400
