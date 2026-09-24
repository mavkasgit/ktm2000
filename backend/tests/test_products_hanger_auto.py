"""Тесты модели данных артикула: per-length quantity_per_hanger, периметр/габарит (#60).

Поведение через API-контракт create/patch/out products:
- quantity_per_hanger — словарь по длинам {length_mm: {auto, manual}}, авто и ручное раздельно.
- Режим подвеса явный (#127): hanger_mode хранится в attributes; при
  создании без режима выводится из данных (периметр И габарит → auto).
- Используется значение выбранного режима; ручное никогда не затирается.
- Валидация perimeter_mm/mount_width_mm >0 → 422.
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
    lengths_mm = overrides.pop("lengths_mm", None)
    primary_length_mm = overrides.pop("primary_length_mm", None)
    if lengths_mm is not None:
        ordered_lengths_mm = sorted(lengths_mm)
        primary_index = ordered_lengths_mm.index(
            primary_length_mm if primary_length_mm is not None else ordered_lengths_mm[0]
        )
        data["lengths"] = [
            {
                "length_mm": length_mm,
                "raw_length_mm": None,
                "is_primary": index == primary_index,
            }
            for index, length_mm in enumerate(ordered_lengths_mm)
        ]
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
async def test_list_qty_filter_uses_auto_value(client, session) -> None:
    """Фильтр qty_from/qty_to работает по значению режима артикула (#127)."""
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


# ─── Явный режим подвеса (#127) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_derives_hanger_mode_from_fields(client, session) -> None:
    """Создание без явного режима: периметр И габарит → auto, иначе manual."""
    auto = await client.post(
        "/api/products",
        json=_payload("RAW-MODE-AUTO", perimeter_mm=64.2, mount_width_mm=19.35, lengths_mm=[2800]),
    )
    assert auto.status_code == 201, auto.text
    assert auto.json()["hanger_mode"] == "auto"

    manual = await client.post(
        "/api/products",
        json=_payload("RAW-MODE-MAN", lengths_mm=[2800], quantity_per_hanger={"2800": {"manual": 10}}),
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["hanger_mode"] == "manual"

    # Явный режим важнее данных: поля заполнены, но режим manual.
    explicit = await client.post(
        "/api/products",
        json=_payload(
            "RAW-MODE-EXPL",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800],
            hanger_mode="manual",
        ),
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["hanger_mode"] == "manual"


@pytest.mark.asyncio
async def test_mode_switch_changes_effective_value(client, session) -> None:
    """Значение следует за режимом; авто не затирает ручное и наоборот."""
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-MODE-SWITCH",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800],
            quantity_per_hanger={"2800": {"manual": 55}},
        ),
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert resp.json()["hanger_mode"] == "auto"

    async def _scalar() -> int | None:
        product = (await session.execute(
            select(Product).options(selectinload(Product.lengths)).where(Product.id == pid)
        )).scalar_one()
        return product.quantity_per_hanger

    # Режим auto → авто-значение (72), ручное 55 хранится отдельно.
    assert await _scalar() == 72

    patched = await client.patch(f"/api/products/{pid}", json={"hanger_mode": "manual"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["hanger_mode"] == "manual"
    qph = patched.json()["quantity_per_hanger"]
    assert qph["2800"]["auto"] == 72  # авто не затёрлось сменой режима
    assert qph["2800"]["manual"] == 55
    assert await _scalar() == 55

    # Обратно в auto — снова авто-значение.
    patched = await client.patch(f"/api/products/{pid}", json={"hanger_mode": "auto"})
    assert patched.status_code == 200, patched.text
    assert await _scalar() == 72


@pytest.mark.asyncio
async def test_list_qty_filter_follows_mode(client, session) -> None:
    """Фильтр списка берёт значение выбранного режима, не «авто > ручное» (#127)."""
    # Поля заполнены, но режим явно manual → в фильтре участвует ручное.
    resp = await client.post(
        "/api/products",
        json=_payload(
            "RAW-QTY-MODE",
            perimeter_mm=64.2,
            mount_width_mm=19.35,
            lengths_mm=[2800],
            quantity_per_hanger={"2800": {"manual": 60}},
            hanger_mode="manual",
        ),
    )
    assert resp.status_code == 201, resp.text

    # Авто-значение было бы 72 — диапазон 65..80 его ловил бы, ручное 60 — нет.
    hit = await client.get("/api/products?qty_from=65&qty_to=80")
    assert hit.status_code == 200
    assert "RAW-QTY-MODE" not in {i["sku"] for i in hit.json()["items"]}

    hit = await client.get("/api/products?qty_from=55&qty_to=65")
    assert hit.status_code == 200
    assert "RAW-QTY-MODE" in {i["sku"] for i in hit.json()["items"]}


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
    assert body["lengths"] == [
        {"length_mm": 2780.0, "raw_length_mm": None, "is_primary": True},
        {"length_mm": 3500.0, "raw_length_mm": None, "is_primary": False},
    ]


@pytest.mark.asyncio
async def test_create_primary_explicit(client, session) -> None:
    """Явный is_primary в реестре сохраняется."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-002", lengths_mm=[2780, 3500], primary_length_mm=3500),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lengths"] == [
        {"length_mm": 2780.0, "raw_length_mm": None, "is_primary": False},
        {"length_mm": 3500.0, "raw_length_mm": None, "is_primary": True},
    ]

    pls = (await session.execute(
        select(ProductLength).where(ProductLength.product_id == resp.json()["id"])
    )).scalars().all()
    primary = [pl for pl in pls if pl.is_primary]
    assert len(primary) == 1
    assert primary[0].length_mm == 3500


@pytest.mark.asyncio
async def test_patch_switch_primary(client, session) -> None:
    """PATCH реестра переключает основную; ручное значение следует за ней."""
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
    assert resp.json()["lengths"][0]["is_primary"] is True
    assert resp.json()["quantity_per_hanger"]["2780"]["manual"] == 40

    patched = await client.patch(
        f"/api/products/{pid}",
        json={
            "lengths": [
                {"length_mm": 2780, "is_primary": False},
                {"length_mm": 3500, "is_primary": True},
            ]
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["lengths"][1]["is_primary"] is True

    product = (await session.execute(
        select(Product).options(selectinload(Product.lengths)).where(Product.id == pid)
    )).scalar_one()
    assert product.quantity_per_hanger == 20


@pytest.mark.asyncio
async def test_patch_multiple_primary_lengths_is_422(client, session) -> None:
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-PRIM-004", lengths_mm=[2780]),
    )
    assert resp.status_code == 201
    pid = resp.json()["id"]

    resp = await client.patch(
        f"/api/products/{pid}",
        json={
            "lengths": [
                {"length_mm": 2780, "is_primary": True},
                {"length_mm": 3500, "is_primary": True},
            ]
        },
    )
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

    resp = await client.patch(
        f"/api/products/{pid}",
        json={
            "lengths": [
                {"length_mm": 3500, "is_primary": True},
                {"length_mm": 4000, "is_primary": False},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lengths"][0]["is_primary"] is True

    resp = await client.patch(
        f"/api/products/{pid}",
        json={
            "lengths": [
                {"length_mm": 2780, "is_primary": True},
                {"length_mm": 4000, "is_primary": False},
            ]
        },
    )
    assert resp.status_code == 200
    # Прежней основной нет — новая основная — первая по возрастанию.
    assert resp.json()["lengths"][0]["is_primary"] is True


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
async def test_duplicate_lengths_rejected(client, session) -> None:
    """Дубли и неположительные нормальные длины отклоняются API."""
    resp = await client.post(
        "/api/products",
        json=_payload("RAW-DUP-001", lengths_mm=[3500, 3500]),
    )
    assert resp.status_code == 422, resp.text

    resp = await client.post(
        "/api/products",
        json=_payload("RAW-DUP-002", lengths_mm=[2780, -5]),
    )
    assert resp.status_code == 422, resp.text
