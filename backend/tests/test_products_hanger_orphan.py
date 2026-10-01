"""Норма-сирота: ручная N под длиной, которой нет в реестре артикула (ADR-0047, #217).

Поведение через API-контракт PATCH /api/products/{id}:
- правка карточки не стирает молча значение под несогласованным ключом —
  запрос отклоняется с объяснением, что норма не применима ни к одной длине;
- блокировка снимается, когда значение удалено или длина введена в реестр;
- линейный артикул не подставляет ручную N из «единственной записи», у листа
  (dimension_state area/volume) подставляет — длина у него одна по определению.
"""
from __future__ import annotations

import pytest
from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _payload(sku: str, **overrides) -> dict:
    data = {
        "sku": sku,
        "name": sku,
        "type": "component",
        "unit": "pcs",
        "hanger_mode": "manual",
    }
    data.update(overrides)
    return data


async def _force_norm_dict(session: AsyncSession, product_id: int, value: dict) -> None:
    """Записать словарь норм в обход API — legacy-дефект из ADR-0047 (2750 при 2700)."""
    product = await session.get(Product, product_id)
    assert product is not None
    product.quantity_per_hanger = value
    await session.commit()


@pytest.mark.asyncio
async def test_patch_with_orphan_norm_key_is_rejected(client, session: AsyncSession) -> None:
    """Ключ нормы, которого нет в реестре длин, блокирует правку карточки."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-001",
            lengths=[{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
            quantity_per_hanger={"2700": {"manual": 62}},
        ),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    await _force_norm_dict(session, pid, {"2750": {"auto": None, "manual": 62}})

    resp = await client.patch(f"/api/products/{pid}", json={"notes": "Правка карточки"})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "2750" in detail
    assert "не применима" in detail

    # Норма на месте: отказ не дал пересобрать словарь (get_db откатывает сессию).
    after = await client.get(f"/api/products/{pid}")
    assert after.json()["quantity_per_hanger"] == {"2750": {"auto": None, "manual": 62}}


@pytest.mark.asyncio
async def test_patch_unblocks_after_orphan_norm_value_removed(client, session: AsyncSession) -> None:
    """Оператор удалил значение — правка проходит, ключ из словаря уходит."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-002",
            lengths=[{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
            quantity_per_hanger={"2700": {"manual": 62}},
        ),
    )
    pid = created.json()["id"]
    await _force_norm_dict(session, pid, {"2750": {"auto": None, "manual": 62}})

    resp = await client.patch(
        f"/api/products/{pid}",
        json={"quantity_per_hanger": {"2750": {"manual": None}}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"] == {"2700": {"auto": None, "manual": None}}


@pytest.mark.asyncio
async def test_patch_unblocks_after_length_matching_orphan_key_added(client, session: AsyncSession) -> None:
    """Длина, введённая в реестр тем же PATCH, снимает блокировку и принимает норму."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-003",
            lengths=[{"length_mm": 2700, "raw_length_mm": 2750, "is_primary": True}],
            quantity_per_hanger={"2700": {"manual": 62}},
        ),
    )
    pid = created.json()["id"]
    await _force_norm_dict(session, pid, {"2750": {"auto": None, "manual": 62}})

    resp = await client.patch(
        f"/api/products/{pid}",
        json={"lengths": [{"length_mm": 2700, "is_primary": True}, {"length_mm": 2750, "is_primary": False}]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quantity_per_hanger"]["2750"]["manual"] == 62


@pytest.mark.asyncio
async def test_patch_keeps_norm_with_exact_registry_key(client) -> None:
    """Норма с точным ключом реестра переживает любую правку карточки."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-004",
            lengths=[{"length_mm": 2700, "is_primary": True}, {"length_mm": 3000, "is_primary": False}],
            quantity_per_hanger={"2700": {"manual": 62}, "3000": {"manual": 40}},
        ),
    )
    pid = created.json()["id"]

    resp = await client.patch(f"/api/products/{pid}", json={"notes": "Проверенная карточка"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"] == {
        "2700": {"auto": None, "manual": 62},
        "3000": {"auto": None, "manual": 40},
    }


@pytest.mark.asyncio
async def test_patch_norm_key_outside_registry_in_payload_is_rejected(client) -> None:
    """Новый ключ не из реестра отклоняется, а не исчезает вместе с запросом."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-007",
            lengths=[{"length_mm": 2700, "is_primary": True}],
            quantity_per_hanger={"2700": {"manual": 62}},
        ),
    )
    pid = created.json()["id"]

    resp = await client.patch(
        f"/api/products/{pid}",
        json={"quantity_per_hanger": {"2700": {"manual": 62}, "2750": {"manual": 5}}},
    )

    assert resp.status_code == 422, resp.text
    assert "2750" in resp.json()["detail"]


async def test_patch_removing_length_with_norm_blocks_until_value_removed(client) -> None:
    """Снятие длины с ручной нормой блокируется; после явного null новая длина
    не наследует значение — у линейного артикула длин много (ADR-0047 п. 3)."""
    created = await client.post(
        "/api/products",
        json=_payload(
            "RAW-ORPHAN-005",
            lengths=[{"length_mm": 3000, "is_primary": True}],
            quantity_per_hanger={"3000": {"manual": 50}},
        ),
    )
    pid = created.json()["id"]
    new_lengths = [{"length_mm": 3050, "is_primary": True}]

    # Норма под снятой длиной — ручной ввод: молча уходить вместе с ней нельзя.
    blocked = await client.patch(f"/api/products/{pid}", json={"lengths": new_lengths})
    assert blocked.status_code == 422, blocked.text
    assert "3000" in blocked.json()["detail"]

    # Оператор удалил значение — правка проходит, и единственная запись НЕ
    # продлевается на новую длину: у линейного артикула длин много.
    resp = await client.patch(
        f"/api/products/{pid}",
        json={"lengths": new_lengths, "quantity_per_hanger": {"3000": {"manual": None}}},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"] == {"3050": {"auto": None, "manual": None}}


@pytest.mark.asyncio
async def test_sheet_norm_follows_new_sheet_length(client, session: AsyncSession) -> None:
    """У листа длина одна по определению: смена полотна не теряет ручную норму."""
    for code in ("length_mm", "width_mm"):
        session.add(DimensionType(code=code, name=code, unit="мм", value_type="number"))
    await session.flush()
    created = await client.post(
        "/api/products",
        json=_payload("RAW-ORPHAN-006", dimension_state="area"),
    )
    pid = created.json()["id"]
    for code, value in (("length_mm", 1000.0), ("width_mm", 500.0)):
        dim_type = await session.scalar(select(DimensionType).where(DimensionType.code == code))
        session.add(
            ProductDimension(product_id=pid, dimension_type_id=dim_type.id, default_value=value)
        )
    await session.commit()

    saved = await client.patch(
        f"/api/products/{pid}",
        json={"hanger_mode": "manual", "quantity_per_hanger": {"1000": {"manual": 5}}},
    )
    assert saved.status_code == 200, saved.text
    length_type_id = await session.scalar(
        select(DimensionType.id).where(DimensionType.code == "length_mm")
    )
    link_id = await session.scalar(
        select(ProductDimension.id).where(
            ProductDimension.product_id == pid,
            ProductDimension.dimension_type_id == length_type_id,
        )
    )

    resp = await client.patch(
        f"/api/products/{pid}/dimensions/{link_id}",
        json={"default_value": 2000.0},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(f"/api/products/{pid}", json={"notes": "Смена полотна"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_per_hanger"]["2000"]["manual"] == 5
