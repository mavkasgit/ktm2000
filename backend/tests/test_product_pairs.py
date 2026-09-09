"""Пары сырьевых артикулов (ADR-0023, #146): модель, pairs-API, целостность.

Модель: канонический порядок a<b, уникальность неупорядоченной пары.
API: симметричное создание/редактирование из любого из двух артикулов,
ручная N строго в пересечении длин A и B, выведенный ``is_paired_profile``.
Целостность: артикул в паре нельзя удалить/деактивировать до разрыва пары.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductLength, ProductPair, ProductType


async def _make_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str | None = None,
    lengths_mm: list[float] | None = None,
    **attrs,
) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.component,
        unit="шт",
        **attrs,
    )
    session.add(product)
    await session.flush()
    for length_mm in lengths_mm or []:
        session.add(ProductLength(product_id=product.id, length_mm=length_mm))
    await session.flush()
    return product


async def _make_pair(
    session: AsyncSession,
    a: Product,
    b: Product,
    quantity_per_hanger: dict | None = None,
) -> ProductPair:
    pair = ProductPair(
        product_a_id=min(a.id, b.id),
        product_b_id=max(a.id, b.id),
        quantity_per_hanger=quantity_per_hanger or {},
    )
    session.add(pair)
    await session.flush()
    return pair


# ─── Модель: констрейнты ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unordered_pair_unique(session: AsyncSession) -> None:
    """Уникальность неупорядоченной пары: (1,2) и (2,1) — одна связь."""
    a = await _make_product(session, sku="PAIR-U-A")
    b = await _make_product(session, sku="PAIR-U-B")
    session.add(ProductPair(product_a_id=a.id, product_b_id=b.id))
    await session.commit()

    session.add(ProductPair(product_a_id=b.id, product_b_id=a.id))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_canonical_order_enforced(session: AsyncSession) -> None:
    """Канонический порядок a<b держит CheckConstraint."""
    a = await _make_product(session, sku="PAIR-C-A")
    b = await _make_product(session, sku="PAIR-C-B")
    session.add(ProductPair(product_a_id=max(a.id, b.id), product_b_id=min(a.id, b.id)))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_several_pairs_per_product_allowed(session: AsyncSession) -> None:
    """Несколько разных пар на один артикул разрешены."""
    a = await _make_product(session, sku="PAIR-M-A")
    b = await _make_product(session, sku="PAIR-M-B")
    c = await _make_product(session, sku="PAIR-M-C")
    session.add(ProductPair(product_a_id=a.id, product_b_id=b.id))
    await session.commit()

    session.add(ProductPair(product_a_id=min(a.id, c.id), product_b_id=max(a.id, c.id)))
    await session.commit()

    pairs = (await session.execute(select(ProductPair))).scalars().all()
    assert len(pairs) == 2


# ─── Pairs-API ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_pair_canonical_and_symmetric(client, session: AsyncSession) -> None:
    """Создание из любого из двух артикулов → одна каноническая запись."""
    a = await _make_product(session, sku="PAIR-API-A", lengths_mm=[2500.0, 2780.0])
    b = await _make_product(session, sku="PAIR-API-B", lengths_mm=[2500.0, 3000.0])
    await session.commit()

    resp = await client.post(f"/api/products/{a.id}/pairs", json={"partner_product_id": b.id})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["product_a_id"] == min(a.id, b.id)
    assert body["product_b_id"] == max(a.id, b.id)
    assert body["partner"]["sku"] == "PAIR-API-B"
    # Длины пары = пересечение длин A и B
    assert body["lengths"] == [2500.0]

    # Симметрично: тот же pair.id из формы партнёра
    resp_sym = await client.post(f"/api/products/{b.id}/pairs", json={"partner_product_id": a.id})
    assert resp_sym.status_code == 409  # уже существует

    listed = await client.get(f"/api/products/{b.id}/pairs")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
    assert items[0]["partner"]["sku"] == "PAIR-API-A"

    # Создание дубликата с другой стороны — та же каноническая пара
    dup = await client.post(f"/api/products/{a.id}/pairs", json={"partner_product_id": b.id})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_create_pair_rejects_self_and_missing_partner(client, session: AsyncSession) -> None:
    a = await _make_product(session, sku="PAIR-SELF-A")
    await session.commit()

    resp_self = await client.post(f"/api/products/{a.id}/pairs", json={"partner_product_id": a.id})
    assert resp_self.status_code == 422

    resp_missing = await client.post(f"/api/products/{a.id}/pairs", json={"partner_product_id": 999999})
    assert resp_missing.status_code == 404


@pytest.mark.asyncio
async def test_create_pair_without_common_lengths_allowed_empty(client, session: AsyncSession) -> None:
    """Без общих длин пара создаётся как намерение: 201, lengths == []."""
    a = await _make_product(session, sku="PAIR-NOV-A", lengths_mm=[2780.0])
    b = await _make_product(session, sku="PAIR-NOV-B", lengths_mm=[3000.0])
    await session.commit()

    resp = await client.post(f"/api/products/{a.id}/pairs", json={"partner_product_id": b.id})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lengths"] == []
    assert body["quantity_per_hanger"] == {}

    listed = await client.get(f"/api/products/{a.id}/pairs")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_manual_n_only_within_intersection(client, session: AsyncSession) -> None:
    a = await _make_product(session, sku="PAIR-N-A", lengths_mm=[2500.0, 2780.0])
    b = await _make_product(session, sku="PAIR-N-B", lengths_mm=[2500.0, 3000.0])
    await session.commit()

    # Ручная N по длине вне пересечения — 422
    resp_bad = await client.post(
        f"/api/products/{a.id}/pairs",
        json={"partner_product_id": b.id, "quantity_per_hanger": {"2780": {"manual": 5}}},
    )
    assert resp_bad.status_code == 422

    resp = await client.post(
        f"/api/products/{a.id}/pairs",
        json={"partner_product_id": b.id, "quantity_per_hanger": {"2500": {"manual": 5}}},
    )
    assert resp.status_code == 201, resp.text
    pair_id = resp.json()["id"]
    assert resp.json()["quantity_per_hanger"]["2500"]["manual"] == 5

    # Замена ручной N симметрично из формы партнёра
    resp_patch = await client.patch(
        f"/api/products/{b.id}/pairs/{pair_id}",
        json={"quantity_per_hanger": {"2500": {"manual": 7}}},
    )
    assert resp_patch.status_code == 200, resp_patch.text
    assert resp_patch.json()["quantity_per_hanger"]["2500"]["manual"] == 7

    # Ручная N вне пересечения при патче — 422
    resp_patch_bad = await client.patch(
        f"/api/products/{b.id}/pairs/{pair_id}",
        json={"quantity_per_hanger": {"3000": {"manual": 7}}},
    )
    assert resp_patch_bad.status_code == 422

    # Удаление из формы любого из двух артикулов
    resp_del = await client.delete(f"/api/products/{a.id}/pairs/{pair_id}")
    assert resp_del.status_code == 204
    assert (await client.get(f"/api/products/{b.id}/pairs")).json() == []


@pytest.mark.asyncio
async def test_pair_auto_only_when_both_auto(client, session: AsyncSession) -> None:
    """Режим пары выведенный: авто считается живьём, только если оба auto."""
    a = await _make_product(
        session, sku="PAIR-AUTO-A", lengths_mm=[2500.0],
        perimeter_mm=64.2, mount_width_mm=19.35,
    )
    b = await _make_product(
        session, sku="PAIR-AUTO-B", lengths_mm=[2500.0],
        perimeter_mm=68.0, mount_width_mm=20.0,
    )
    # hanger_mode default 'auto' — движок: by_area = floor(13/0.3305) = 39,
    # by_size = floor(2900/(39.35+40)) = 36 → total = 36.
    await session.commit()
    pair = await _make_pair(session, a, b)
    await session.commit()

    resp = await client.get(f"/api/products/{a.id}/pairs")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["quantity_per_hanger"]["2500"]["auto"] == 36
    assert body["quantity_per_hanger"]["2500"]["manual"] is None

    # Один из артикулов в manual-режиме → авто пары нет
    a.hanger_mode = "manual"
    await session.commit()
    resp = await client.get(f"/api/products/{a.id}/pairs")
    assert resp.json()[0]["quantity_per_hanger"]["2500"]["auto"] is None


@pytest.mark.asyncio
async def test_pair_lengths_follow_length_changes(client, session: AsyncSession) -> None:
    """Длины пары = пересечение живьём: длина ушла из артикула — пара на ней не существует."""
    a = await _make_product(session, sku="PAIR-LEN-A", lengths_mm=[2500.0, 2780.0])
    b = await _make_product(session, sku="PAIR-LEN-B", lengths_mm=[2500.0])
    pair = await _make_pair(session, a, b, {"2500": {"auto": None, "manual": 5}})
    await session.commit()

    resp = await client.get(f"/api/products/{a.id}/pairs")
    assert resp.json()[0]["lengths"] == [2500.0]

    # Длина 2500 удалена у партнёра → пересечение пустое: пара «вне
    # пересечения не существует» (lengths пуст, N нет), но видна в списке —
    # иначе её нельзя было бы увидеть и разорвать, а она держит удаление.
    resp_patch = await client.patch(f"/api/products/{b.id}", json={"lengths_mm": [3000.0]})
    assert resp_patch.status_code == 200, resp_patch.text
    resp = await client.get(f"/api/products/{a.id}/pairs")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["lengths"] == []
    assert resp.json()[0]["quantity_per_hanger"] == {}

    # Длина вернулась — пара снова существует вместе с ручной N
    await client.patch(f"/api/products/{b.id}", json={"lengths_mm": [2500.0]})
    resp = await client.get(f"/api/products/{a.id}/pairs")
    assert len(resp.json()) == 1
    assert resp.json()[0]["lengths"] == [2500.0]
    assert resp.json()[0]["quantity_per_hanger"]["2500"]["manual"] == 5


# ─── Выведенный is_paired_profile ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_paired_profile_derived_from_pairs(client, session: AsyncSession) -> None:
    a = await _make_product(session, sku="PAIR-FLG-A")
    b = await _make_product(session, sku="PAIR-FLG-B")
    c = await _make_product(session, sku="PAIR-FLG-C")
    await session.commit()

    resp = await client.get("/api/products", params={"sku": "PAIR-FLG"})
    assert all(item["is_paired_profile"] is False for item in resp.json()["items"])

    await _make_pair(session, a, b)
    await session.commit()
    # expire_on_commit=False: уже загруженные объекты держат прежнее значение
    # выведенного флага — сбрасываем, чтобы второй GET перечитал EXISTS.
    session.expire_all()

    resp = await client.get("/api/products", params={"sku": "PAIR-FLG"})
    flags = {item["sku"]: item["is_paired_profile"] for item in resp.json()["items"]}
    assert flags == {"PAIR-FLG-A": True, "PAIR-FLG-B": True, "PAIR-FLG-C": False}

    # Фильтр по выведенному флагу
    resp = await client.get("/api/products", params={"sku": "PAIR-FLG", "is_paired_profile": "true"})
    assert {item["sku"] for item in resp.json()["items"]} == {"PAIR-FLG-A", "PAIR-FLG-B"}

    # Разрыв пары — флаг гаснет
    pair = (await session.execute(select(ProductPair))).scalar_one()
    await session.delete(pair)
    await session.commit()
    session.expire_all()
    resp = await client.get("/api/products", params={"sku": "PAIR-FLG", "is_paired_profile": "true"})
    assert resp.json()["items"] == []


# ─── Целостность: удаление/деактивация артикула в паре ──────────────────────


@pytest.mark.asyncio
async def test_delete_product_in_pair_409_then_allowed(client, session: AsyncSession) -> None:
    a = await _make_product(session, sku="PAIR-DEL-A")
    b = await _make_product(session, sku="PAIR-DEL-B")
    await _make_pair(session, a, b)
    await session.commit()

    resp = await client.delete(f"/api/products/{a.id}")
    assert resp.status_code == 409
    assert "пары артикула" in resp.json()["detail"] or "в паре" in resp.json()["detail"]

    # Разорвали пару — удаление проходит
    pairs = (await session.execute(select(ProductPair))).scalars().all()
    for pair in pairs:
        await session.delete(pair)
    await session.commit()
    resp = await client.delete(f"/api/products/{a.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_deactivate_product_in_pair_409_then_allowed(client, session: AsyncSession) -> None:
    a = await _make_product(session, sku="PAIR-DEA-A")
    b = await _make_product(session, sku="PAIR-DEA-B")
    await _make_pair(session, a, b)
    await session.commit()

    resp = await client.patch(f"/api/products/{a.id}", json={"is_active": False})
    assert resp.status_code == 409
    assert "пары артикула" in resp.json()["detail"] or "в паре" in resp.json()["detail"]

    # Артикул вне пары деактивируется свободно
    resp = await client.patch(f"/api/products/{b.id}", json={"is_active": True})
    assert resp.status_code == 200

    pair = (await session.execute(select(ProductPair))).scalar_one()
    await session.delete(pair)
    await session.commit()
    resp = await client.patch(f"/api/products/{a.id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_create_product_accepts_no_paired_flag(client, session: AsyncSession) -> None:
    """is_paired_profile больше не поле создания — флаг только выведенный."""
    resp = await client.post(
        "/api/products",
        json={"sku": "PAIR-CREATE-1", "name": "No flag", "type": "component"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_paired_profile"] is False


# ─── Каталог всех пар — источник витрины расчёта подвесов (#150) ────────────


@pytest.mark.asyncio
async def test_product_pairs_catalog_lists_all(client, session: AsyncSession) -> None:
    """GET /product-pairs: все пары одним списком, без привязки к артикулу."""
    a = await _make_product(
        session, sku="PAIR-CAT-A", lengths_mm=[2500.0, 2780.0],
        perimeter_mm=64.2, mount_width_mm=19.35,
    )
    b = await _make_product(
        session, sku="PAIR-CAT-B", lengths_mm=[2500.0],
        perimeter_mm=68.0, mount_width_mm=20.0,
    )
    c = await _make_product(session, sku="PAIR-CAT-C", lengths_mm=[2780.0])
    await _make_pair(session, a, b, {"2500": {"auto": None, "manual": 5}})
    await _make_pair(session, a, c)
    await session.commit()

    resp = await client.get("/api/product-pairs")
    assert resp.status_code == 200, resp.text
    items = {(item["product_a_id"], item["product_b_id"]): item for item in resp.json()}
    assert len(items) == 2

    ab = items[(min(a.id, b.id), max(a.id, b.id))]
    assert (ab["product_a_id"], ab["product_b_id"]) == (min(a.id, b.id), max(a.id, b.id))
    assert ab["lengths"] == [2500.0]
    # auto живьём (оба auto): движок по сумме периметров/габаритов; ручное из словаря
    assert ab["quantity_per_hanger"]["2500"]["auto"] == 36
    assert ab["quantity_per_hanger"]["2500"]["manual"] == 5

    ac = items[(min(a.id, c.id), max(a.id, c.id))]
    assert ac["lengths"] == [2780.0]
    # у C нет периметра/габарита — авто не считается
    assert ac["quantity_per_hanger"]["2780"]["auto"] is None


@pytest.mark.asyncio
async def test_product_pairs_catalog_pair_without_common_lengths(client, session: AsyncSession) -> None:
    """Пара вне пересечения длин видна с lengths: [] и без N (#150, нюанс #146)."""
    a = await _make_product(session, sku="PAIR-EMPTY-A", lengths_mm=[2500.0])
    b = await _make_product(session, sku="PAIR-EMPTY-B", lengths_mm=[3000.0])
    await _make_pair(session, a, b, {"2500": {"auto": None, "manual": 5}})
    await session.commit()

    resp = await client.get("/api/product-pairs")
    assert resp.status_code == 200
    (item,) = resp.json()
    assert item["lengths"] == []
    assert item["quantity_per_hanger"] == {}


@pytest.mark.asyncio
async def test_product_pairs_catalog_auto_only_when_both_mode_auto(client, session: AsyncSession) -> None:
    """Режим пары выведенный: авто в каталоге — только при auto у обоих."""
    a = await _make_product(
        session, sku="PAIR-MODE-A", lengths_mm=[2500.0],
        perimeter_mm=64.2, mount_width_mm=19.35,
    )
    b = await _make_product(
        session, sku="PAIR-MODE-B", lengths_mm=[2500.0],
        perimeter_mm=68.0, mount_width_mm=20.0, hanger_mode="manual",
    )
    await _make_pair(session, a, b)
    await session.commit()

    resp = await client.get("/api/product-pairs")
    (item,) = resp.json()
    assert item["quantity_per_hanger"]["2500"]["auto"] is None
