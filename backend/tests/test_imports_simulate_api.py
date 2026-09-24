"""Тесты бесфайлового импорта плана `POST /api/imports/excel/simulate`.

Эндпоинт собирает «Упаковочный план» в памяти из переданных строк и прогоняет
его тем же change-set путём, что и upload-импорт `/api/imports/excel`. Здесь
защищаем наблюдаемые контракты: создание позиции, группировку строк раскроя в
одну позицию с несколькими выходами, добавление в существующий план и
валидацию входа (пустые rows / несуществующий / неактивный шаблон).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.models.product import Product, ProductLength, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section

SIMULATE_URL = "/api/imports/excel/simulate"


def _row(
    sku: str,
    *,
    name: str | None = None,
    qty_per_27: float | None = None,
    length_m: float | None = None,
    output_length_m: float | None = None,
    output_qty: float | None = None,
    kind: str | None = "ГП",
) -> dict:
    """Строка «Упаковочного плана» в форме модели SimulatedPlanRow."""
    return {
        "sku": sku,
        "name": name,
        "qty_per_27": qty_per_27,
        "length_m": length_m,
        "output_length_m": output_length_m,
        "output_qty": output_qty,
        "kind": kind,
    }


async def _seed_product_with_route(session, sku: str) -> Product:
    """Продукт + маршрут из трёх секций — чтобы позиция была валидной."""
    product = await session.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        product = Product(
            sku=sku,
            name=f"Product {sku}",
            type=ProductType.finished_good,
            unit="pcs",
        )
        session.add(product)
        product.lengths.append(
            ProductLength(length_mm=2700, is_primary=True)
        )

    sections: list[Section] = []
    for code, name in (("CUT", "Cut"), ("PACKING", "Pack")):
        section = await session.scalar(select(Section).where(Section.code == code))
        if section is None:
            section = Section(code=code, name=name)
            session.add(section)
        sections.append(section)
    await session.flush()

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=index * 10,
            section_id=section.id,
            is_final=index == len(sections),
        )
        session.add(stage)
        await session.flush()
        session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_name=f"Step {index}"))
    await session.flush()
    return product


async def _apply(client, plan_id: int, change_set_id: int) -> dict:
    response = await client.post(
        f"/api/production-plans/{plan_id}/change-sets/{change_set_id}/apply"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _all_positions(client, plan_id: int) -> list[dict]:
    response = await client.get(f"/api/production-plans/{plan_id}/all-positions")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_simulate_single_row_creates_position(client, session) -> None:
    """Одна строка: change set создан, после применения — позиция с нужным
    sku и количеством выхода."""
    await _seed_product_with_route(session, "SIM-ONE")
    await session.commit()

    response = await client.post(
        SIMULATE_URL,
        json={
            "rows": [
                _row(
                    "SIM-ONE",
                    name="Профиль SIM-ONE",
                    qty_per_27=150,
                    length_m=2.7,
                    output_length_m=2.7,
                    output_qty=150,
                )
            ]
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["summary"]["total_positions"] == 1
    assert body["items"][0]["source_sku"] == "SIM-ONE"

    await _apply(client, body["production_plan_id"], body["change_set_id"])

    positions = await _all_positions(client, body["production_plan_id"])
    assert len(positions) == 1
    assert positions[0]["source_sku"] == "SIM-ONE"
    assert Decimal(positions[0]["quantity"]) == Decimal("150")


@pytest.mark.asyncio
async def test_simulate_cut_group_produces_position_with_multiple_outputs(client, session) -> None:
    """Группа раскроя (2 строки одного sku): первая с входом, продолжение —
    только выход. Одна позиция с двумя выходами разных длин и раскладкой."""
    await _seed_product_with_route(session, "SIM-CUT")
    await session.commit()

    response = await client.post(
        SIMULATE_URL,
        json={
            "rows": [
                _row(
                    "SIM-CUT",
                    name="Профиль SIM-CUT",
                    qty_per_27=150,
                    length_m=2.7,
                    output_length_m=0.9,
                    output_qty=350,
                ),
                # Строка-продолжение: тот же sku (обязателен в модели), вход пуст.
                _row("SIM-CUT", output_length_m=1.8, output_qty=50),
            ]
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["summary"]["total_positions"] == 1

    await _apply(client, body["production_plan_id"], body["change_set_id"])

    positions = await _all_positions(client, body["production_plan_id"])
    assert len(positions) == 1
    position = positions[0]
    assert position["source_sku"] == "SIM-CUT"
    assert Decimal(position["quantity"]) == Decimal("400")
    assert [(o["quantity"], o["dimensions"]) for o in position["outputs"]] == [
        ("350", {"length_mm": 900}),
        ("50", {"length_mm": 1800}),
    ]
    assert position["cut_layout"] == {"input": "2,7", "outputs": ["0,9×350", "1,8×50"]}


@pytest.mark.asyncio
async def test_simulate_empty_rows_returns_422(client) -> None:
    response = await client.post(SIMULATE_URL, json={"rows": []})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_simulate_unknown_template_returns_404(client) -> None:
    response = await client.post(
        SIMULATE_URL,
        json={"rows": [_row("SIM-NO-TEMPLATE", output_qty=1)], "template_id": 987654},
    )
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_simulate_inactive_template_returns_400(client, session) -> None:
    template = ImportTemplate(
        name="Inactive Sim Template",
        code="inactive-sim-template",
        is_active=False,
        column_mapping={"sku": {"header": "Артикул", "column": "A"}},
    )
    session.add(template)
    await session.flush()

    response = await client.post(
        SIMULATE_URL,
        json={"rows": [_row("SIM-INACTIVE", output_qty=1)], "template_id": template.id},
    )
    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_simulate_append_to_plan_adds_position_to_existing_plan(client, session) -> None:
    """append_to_plan к существующему плану добавляет позицию в тот же план,
    а не создаёт новый."""
    await _seed_product_with_route(session, "SIM-APP-1")
    await _seed_product_with_route(session, "SIM-APP-2")
    await session.commit()

    first = await client.post(
        SIMULATE_URL,
        json={
            "rows": [
                _row(
                    "SIM-APP-1",
                    name="Профиль SIM-APP-1",
                    qty_per_27=100,
                    length_m=2.7,
                    output_length_m=2.7,
                    output_qty=100,
                )
            ]
        },
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    plan_id = first_body["production_plan_id"]
    await _apply(client, plan_id, first_body["change_set_id"])
    assert len(await _all_positions(client, plan_id)) == 1

    second = await client.post(
        SIMULATE_URL,
        json={
            "mode": "append_to_plan",
            "production_plan_id": plan_id,
            "rows": [
                _row(
                    "SIM-APP-2",
                    name="Профиль SIM-APP-2",
                    qty_per_27=80,
                    length_m=2.7,
                    output_length_m=2.7,
                    output_qty=80,
                )
            ],
        },
    )
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["production_plan_id"] == plan_id

    await _apply(client, plan_id, second_body["change_set_id"])

    positions = await _all_positions(client, plan_id)
    assert {p["source_sku"] for p in positions} == {"SIM-APP-1", "SIM-APP-2"}
