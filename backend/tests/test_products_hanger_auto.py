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
