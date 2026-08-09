"""Тесты модели данных артикула: per-length quantity_per_hanger, периметр/габарит (#60).

Поведение через API-контракт create/patch/out products:
- quantity_per_hanger — словарь по длинам {length_mm: {auto, manual}}, авто и ручное раздельно.
- Авто-режим data-driven: оба поля perimeter_mm И mount_width_mm → авто для всех длин.
- Ручное значение не затирается при авто — остаётся fallback.
- Валидация perimeter_mm/mount_width_mm >0 → 422.
- Скаляр в attributes (миграция) → {первая_длина: {auto: null, manual: значение}}.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product, ProductLength, ProductType


def _payload(sku: str, **overrides) -> dict:
    data = {
        "sku": sku,
        "name": sku,
        "type": "component",
        "unit": "pcs",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_create_with_auto_fields_computes_per_length(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-AUTO-001",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800, 3500],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["perimeter_mm"] == 64.2
    assert body["mount_width_mm"] == 19.35

    qph = body["quantity_per_hanger"]
    assert qph is not None
    # 2800 → по формуле заказчика ЮП-460: by_area=72, by_size=72, total=72
    assert qph["2800"]["auto"] == 72
    assert qph["2800"]["manual"] is None
    # 3500 → auto считается по той же формуле
    assert qph["3500"]["auto"] is not None
    assert qph["3500"]["auto"] > 0
    assert qph["3500"]["manual"] is None


@pytest.mark.asyncio
async def test_create_manual_only_has_null_auto(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-MAN-001",
            lengths_mm=[2800],
            quantity_per_hanger={"2800": {"manual": 60}},
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    qph = body["quantity_per_hanger"]
    assert qph["2800"]["auto"] is None
    assert qph["2800"]["manual"] == 60


@pytest.mark.asyncio
async def test_manual_fallback_not_overwritten_by_auto(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-FALLBACK-001",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800],
            quantity_per_hanger={"2800": {"manual": 55}},
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    qph = body["quantity_per_hanger"]
    # Авто посчиталось, ручной fallback сохранился отдельно.
    assert qph["2800"]["auto"] == 72
    assert qph["2800"]["manual"] == 55


@pytest.mark.asyncio
async def test_clearing_field_returns_to_manual(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-CLEAR-001",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800],
            quantity_per_hanger={"2800": {"manual": 50}},
        ),
    )
    assert resp.status_code == 201
    product_id = resp.json()["id"]

    # Стираем габарит → авто-режим выключен, auto → null, manual сохранён.
    resp = await client.patch(f"/api/products/{product_id}", json={"mount_width_mm": None})
    assert resp.status_code == 200, resp.text
    qph = resp.json()["quantity_per_hanger"]
    assert qph["2800"]["auto"] is None
    assert qph["2800"]["manual"] == 50


@pytest.mark.asyncio
async def test_patch_recomputes_auto_after_perimeter_change(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PATCH-001", perimeter_mm=64.2, mount_width_mm=19.35, lengths_mm=[2800]),
    )
    assert resp.status_code == 201
    product_id = resp.json()["id"]
    assert resp.json()["quantity_per_hanger"]["2800"]["auto"] == 72

    # Увеличиваем периметр в 2 раза → авто падает.
    resp = await client.patch(f"/api/products/{product_id}", json={"perimeter_mm": 128.4})
    assert resp.status_code == 200, resp.text
    qph = resp.json()["quantity_per_hanger"]
    assert qph["2800"]["auto"] == 36
    assert qph["2800"]["manual"] is None


@pytest.mark.asyncio
async def test_perimeter_mount_width_validation_gt0(client, session) -> None:
    for field in ("perimeter_mm", "mount_width_mm"):
        resp = await client.post(
            "/api/products",
            json=_payload(f"RAW-BAD-{field}", **{field: 0}, lengths_mm=[2800]),
        )
        assert resp.status_code == 422, f"expected 422 for {field}=0"

        resp = await client.post(
            "/api/products",
            json=_payload(f"RAW-NEG-{field}", **{field: -5}, lengths_mm=[2800]),
        )
        assert resp.status_code == 422, f"expected 422 for {field}=-5"


@pytest.mark.asyncio
async def test_cross_field_incompatibility_returns_422(client, session) -> None:
    # mount_width + gap (20) > rod_length (1450) → 422.
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-CROSS-001", perimeter_mm=64.2, mount_width_mm=2000, lengths_mm=[2800]),
    )
    assert resp.status_code == 422, resp.text
    assert "Несовместимые данные" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scalar_migrates_to_primary_length(client, session) -> None:
    """Скаляр в attributes (как после миграции до нормализации) → per-length dict."""
    product = Product(
        sku="RAW-LEGACY-001",
        name="Legacy scalar",
        type=ProductType.component,
        unit="pcs",
    )
    product.quantity_per_hanger = 25
    session.add(product)
    await session.flush()
    session.add(ProductLength(product_id=product.id, length_mm=2800))
    session.add(ProductLength(product_id=product.id, length_mm=3500))
    await session.commit()

    # Legacy-скаляр хранится как bare {auto:null, manual:25}; out → {первая_длина: ...}
    resp = await client.get(f"/api/products/{product.id}")
    assert resp.status_code == 200
    qph = resp.json()["quantity_per_hanger"]
    assert qph["2800"]["auto"] is None
    assert qph["2800"]["manual"] == 25
    # Остальные длины не входят в dict (ручной fallback только для первой).
    assert "3500" not in qph


@pytest.mark.asyncio
async def test_main_quantity_per_hanger_legacy(client, session) -> None:
    """main_quantity_per_hanger() для обратной совместимости (план-импорт)."""
    product = Product(
        sku="RAW-MAIN-001",
        name="Main",
        type=ProductType.component,
        unit="pcs",
    )
    product.quantity_per_hanger = 40
    session.add(product)
    await session.flush()
    session.add(ProductLength(product_id=product.id, length_mm=2780))
    await session.commit()

    await session.refresh(product)
    assert product.main_quantity_per_hanger() == 40
    assert product.quantity_per_hanger_for_length(2780) == 40


@pytest.mark.asyncio
async def test_legacy_scalar_without_lengths_not_crash(client, session) -> None:
    """Legacy-скаляр без product_lengths (миграция не трогает) — out не падает."""
    product = Product(
        sku="RAW-NOLEN-001",
        name="No lengths",
        type=ProductType.component,
        unit="pcs",
    )
    product.quantity_per_hanger = 33
    session.add(product)
    await session.commit()

    resp = await client.get(f"/api/products/{product.id}")
    assert resp.status_code == 200
    # Длин нет — раскрыть per-length не во что; value остаётся в attributes.
    assert resp.json()["quantity_per_hanger"] is None
    await session.refresh(product)
    assert product.quantity_per_hanger == 33


@pytest.mark.asyncio
async def test_list_qty_filter_uses_auto_value(client, session) -> None:
    """Фильтр qty_from/qty_to работает по авто-значению (приоритет авто > ручное)."""
    auto = await client.post(
        "/api/products",
        json=_payload("RAW-QTY-AUTO", perimeter_mm=64.2, mount_width_mm=19.35, lengths_mm=[2800]),
    )
    assert auto.status_code == 201
    assert auto.json()["quantity_per_hanger"]["2800"]["auto"] == 72

    manual = await client.post(
        "/api/products",
        json=_payload("RAW-QTY-MAN", lengths_mm=[2800], quantity_per_hanger={"2800": {"manual": 10}}),
    )
    assert manual.status_code == 201

    resp = await client.get("/api/products?qty_from=50&qty_to=80")
    assert resp.status_code == 200
    skus = {item["sku"] for item in resp.json()["items"]}
    assert "RAW-QTY-AUTO" in skus
    assert "RAW-QTY-MAN" not in skus


# ─── Основная длина (#81) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_primary_defaults_to_first_length(client, session) -> None:
    """При создании без явного выбора основная — первая длина по возрастанию."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-001", lengths_mm=[3500, 2780]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lengths_mm"] == [2780, 3500]
    assert body["primary_length_mm"] == 2780


@pytest.mark.asyncio
async def test_create_primary_explicit(client, session) -> None:
    """Явный primary_length_mm при создании сохраняется."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-002", lengths_mm=[2780, 3500], primary_length_mm=3500),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["primary_length_mm"] == 3500

    pls = (await session.execute(
        select(ProductLength).where(ProductLength.product_id == resp.json()["id"])
    )).scalars().all()
    primary = [pl for pl in pls if pl.is_primary]
    assert len(primary) == 1
    assert primary[0].length_mm == 3500


@pytest.mark.asyncio
async def test_patch_switch_primary(client, session) -> None:
    """PATCH primary_length_mm переключает основную; legacy-скаляр следует за ней."""
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-PRIM-003",
            lengths_mm=[2780, 3500],
            quantity_per_hanger={"2780": {"manual": 40}, "3500": {"manual": 20}},
        ),
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert resp.json()["primary_length_mm"] == 2780
    assert resp.json()["quantity_per_hanger"]["2780"]["manual"] == 40

    patched = await client.patch(f"/api/products/{pid}", json={"primary_length_mm": 3500})
    assert patched.status_code == 200, patched.text
    assert patched.json()["primary_length_mm"] == 3500

    product = (await session.execute(
        select(Product).options(selectinload(Product.lengths)).where(Product.id == pid)
    )).scalar_one()
    assert product.main_quantity_per_hanger() == 20


@pytest.mark.asyncio
async def test_patch_primary_not_a_length_is_422(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-004", lengths_mm=[2780]),
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]

    resp = await client.patch(f"/api/products/{pid}", json={"primary_length_mm": 9999})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_lengths_keeps_primary(client, session) -> None:
    """Замена длин сохраняет основную, если она осталась в списке."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-005", lengths_mm=[2780, 3500], primary_length_mm=3500),
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]

    resp = await client.patch(f"/api/products/{pid}", json={"lengths_mm": [3500, 4000]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["primary_length_mm"] == 3500

    resp = await client.patch(f"/api/products/{pid}", json={"lengths_mm": [2780, 4000]})
    assert resp.status_code == 200
    # Прежней основной нет — новая основная = первая по возрастанию.
    assert resp.json()["primary_length_mm"] == 2780


@pytest.mark.asyncio
async def test_sort_by_quantity_per_hanger_uses_primary(client, session) -> None:
    """Сортировка по кол-ву на подвесе использует выбранную основную (#81)."""
    a = await client.post(
        "/api/products",
        json=_payload(
            "RAW-PRIM-SORT-A",
            lengths_mm=[2780, 3500],
            quantity_per_hanger={"2780": {"manual": 10}, "3500": {"manual": 100}},
            primary_length_mm=3500,
        ),
    )
    assert a.status_code == 201

    b = await client.post(
        "/api/products",
        json=_payload(
            "RAW-PRIM-SORT-B",
            lengths_mm=[2780, 3500],
            quantity_per_hanger={"2780": {"manual": 50}, "3500": {"manual": 50}},
        ),
    )
    assert b.status_code == 201

    resp = await client.get("/api/products?sort=quantity_per_hanger:asc")
    assert resp.status_code == 200
    skus = [item["sku"] for item in resp.json()["items"] if item["sku"].startswith("RAW-PRIM-SORT")]
    assert skus == ["RAW-PRIM-SORT-B", "RAW-PRIM-SORT-A"]


@pytest.mark.asyncio
async def test_legacy_scalar_preserved_with_loaded_lengths(client, session) -> None:
    """Legacy bare-словарь не теряется, когда lengths загружены (#81 регрессия).

    _primary_hanger_length_key для bare {auto, manual} должен вернуть None,
    чтобы quantity_per_hanger/main_quantity_per_hanger отдали скаляр.
    """
    product = Product(
        sku="RAW-LEGACY-LEN",
        name="Legacy with lengths",
        type=ProductType.component,
        unit="pcs",
    )
    product.quantity_per_hanger = 40
    session.add(product)
    await session.flush()
    session.add_all([
        ProductLength(product_id=product.id, length_mm=2780, is_primary=True),
        ProductLength(product_id=product.id, length_mm=3500),
    ])
    await session.commit()

    loaded = (await session.execute(
        select(Product).options(selectinload(Product.lengths)).where(Product.id == product.id)
    )).scalar_one()
    assert loaded.main_quantity_per_hanger() == 40
    assert loaded.quantity_per_hanger == 40


@pytest.mark.asyncio
async def test_sort_legacy_scalar_dict_not_crash(client, session) -> None:
    """Сортировка по кол-ву при bare-словаре не падает (регрессия #81)."""
    product = Product(
        sku="RAW-LEGACY-SORT",
        name="Legacy sort",
        type=ProductType.component,
        unit="pcs",
    )
    product.quantity_per_hanger = 33
    session.add(product)
    await session.commit()

    resp = await client.get("/api/products?sort=quantity_per_hanger:asc")
    assert resp.status_code == 200
    skus = {i["sku"] for i in resp.json()["items"]}
    assert "RAW-LEGACY-SORT" in skus


@pytest.mark.asyncio
async def test_duplicate_lengths_rejected(client, session) -> None:
    """Дубли длин → 400 (edge cases; иначе partial unique index ломается)."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-DUP-001", lengths_mm=[3500, 3500]),
    )
    assert resp.status_code == 400, resp.text

    resp = await client.post(
        "/api/products",
        json=_payload("RAW-DUP-002", lengths_mm=[2780, -5]),
    )
    assert resp.status_code == 400, resp.text
