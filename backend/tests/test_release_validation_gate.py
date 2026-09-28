"""Гейт релиза (ADR-0048, тикет #212).

Позиция с невалидной валидацией не уходит в работу: `create_release_batch`
отказывает её, а форс-аппрув переводит валидацию в отдельное состояние
«перекрыта» — вот это состояние гейт пропускает. Валидация читается как
есть, без пересчёта на момент выпуска.

Прогон: ``npm run test:pytest -- tests/test_release_validation_gate.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditEntityType, AuditLog
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.services.plan_generation import create_release_batch
from app.services.production_plan_service import approve_plan_position
from tests.test_bulk_planning import _auth_headers, _make_plan_with_positions, _make_user


#: Этапы маршрута: участок, операция, признак значимости.
_ROUTE_STEPS = (
    ("RAW_STOCK", "STOCK_IN", "Приём", False),
    ("PRESSING", "PRESS_WINDOW", "Прессование", True),
    ("PACKING", "PACK_STRETCH", "Упаковка", False),
)
#: Участки маршрута: код, название, порядок, тип.
_ROUTE_SECTIONS = (
    ("RAW_STOCK", "Склад", 10, "raw_stock"),
    ("PRESSING", "Пресс", 30, "production"),
    ("PACKING", "Упаковка", 80, "production"),
)


async def _seed_route(session) -> ProductionRoute:
    """Маршрут из трёх этапов — минимальный, проходящий проверку маршрута."""
    route = ProductionRoute(name="Гейт релиза: маршрут", is_active=True)
    session.add(route)
    await session.flush()

    for code, name, sort_order, section_type in _ROUTE_SECTIONS:
        session.add(Section(code=code, name=name, sort_order=sort_order, type=section_type, is_active=True))
    await session.flush()

    for sequence, (section_code, op_code, op_name, is_significant) in enumerate(_ROUTE_STEPS, start=1):
        section = await session.scalar(select(Section).where(Section.code == section_code))
        stage = RouteStage(
            route_id=route.id,
            sequence=sequence,
            section_id=section.id,
            is_significant=is_significant,
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=op_code,
                operation_name=op_name,
            )
        )
    await session.flush()
    return route


async def _seed_position(
    session,
    *,
    sku: str,
    validation_status: PlanPositionValidationStatus,
    product_is_active: bool = True,
    position_status: PlanPositionStatus = PlanPositionStatus.approved,
) -> PlanPosition:
    """Позиция плана с готовым маршрутом и заданным состоянием валидации.

    `product_is_active=False` даёт позиции реальную ошибку валидации
    (`product_inactive`) — её пересчитывает `approve_plan_position`.
    """
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=product_is_active
    )
    session.add(product)
    await session.flush()

    route = await _seed_route(session)
    plan = ProductionPlan(plan_no=f"GATE-{sku}", name="План гейта релиза")
    session.add(plan)
    await session.flush()
    plan.status = ProductionPlanStatus.approved

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        output_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.auto.value,
        route_match_quality=PlanPositionRouteMatchQuality.exact.value,
        status=position_status,
        validation_status=validation_status,
        source_payload={},
    )
    session.add(position)
    await session.flush()
    return position


@pytest.mark.asyncio
async def test_approved_position_with_invalid_validation_is_not_released(session) -> None:
    """Утверждённая позиция с невалидной валидацией в партию выпуска не попадает."""
    position = await _seed_position(
        session, sku="FG-GATE-INVALID", validation_status=PlanPositionValidationStatus.invalid
    )

    with pytest.raises(ValueError) as exc_info:
        await create_release_batch(
            session,
            production_plan_id=position.production_plan_id,
            positions=[{"plan_position_id": position.id, "release_quantity": "100"}],
        )

    assert "валидац" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_force_approve_moves_validation_to_overridden(session) -> None:
    """Форс-аппрув с причиной переводит валидацию в «перекрыта», а не в «valid»."""
    position = await _seed_position(
        session,
        sku="FG-GATE-FORCE",
        validation_status=PlanPositionValidationStatus.invalid,
        product_is_active=False,
        position_status=PlanPositionStatus.draft,
    )

    approved = await approve_plan_position(
        session,
        position.production_plan_id,
        position.id,
        force=True,
        reason="Маршрут согласован с технологом, DRILLING исключён по заявке",
    )

    assert approved.validation_status == PlanPositionValidationStatus.overridden
    assert approved.status == PlanPositionStatus.approved
    assert approved.validation_errors, "ошибки валидации остаются на позиции"


@pytest.mark.asyncio
async def test_force_approve_requires_reason(session) -> None:
    """Форс без причины — отказ: обход должен быть записью о согласии человека."""
    position = await _seed_position(
        session,
        sku="FG-GATE-NO-REASON",
        validation_status=PlanPositionValidationStatus.invalid,
        product_is_active=False,
        position_status=PlanPositionStatus.draft,
    )

    with pytest.raises(ValueError) as exc_info:
        await approve_plan_position(session, position.production_plan_id, position.id, force=True)

    assert "причин" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_force_approve_reason_is_written_to_action_journal(session) -> None:
    """Причина форса попадает в журнал действий: обход виден как запись человека."""
    position = await _seed_position(
        session,
        sku="FG-GATE-JOURNAL",
        validation_status=PlanPositionValidationStatus.invalid,
        product_is_active=False,
        position_status=PlanPositionStatus.draft,
    )
    reason = "Артикул временно снят с продаж, отгрузка срочная"

    await approve_plan_position(
        session, position.production_plan_id, position.id, force=True, reason=reason
    )

    entry = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
            AuditLog.entity_id == position.id,
        )
    )
    assert entry is not None
    assert entry.comment == reason
    assert reason in (entry.message or "")


@pytest.mark.asyncio
async def test_overridden_position_is_released(session) -> None:
    """Гейт пропускает именно «перекрыто» — форс остаётся рабочим обходом."""
    position = await _seed_position(
        session, sku="FG-GATE-OVERRIDDEN", validation_status=PlanPositionValidationStatus.overridden
    )
    position.validation_errors = ["route_contains_excluded_step: DRILLING"]

    batch = await create_release_batch(
        session,
        production_plan_id=position.production_plan_id,
        positions=[{"plan_position_id": position.id, "release_quantity": "100"}],
    )

    assert [row["plan_position_id"] for row in batch["positions"]] == [position.id]


@pytest.mark.asyncio
async def test_valid_position_is_released_without_changes(session) -> None:
    """Регресс: позиция без ошибок валидации выпускается как раньше."""
    position = await _seed_position(
        session, sku="FG-GATE-VALID", validation_status=PlanPositionValidationStatus.valid
    )

    batch = await create_release_batch(
        session,
        production_plan_id=position.production_plan_id,
        positions=[{"plan_position_id": position.id, "release_quantity": "100"}],
    )

    assert [row["plan_position_id"] for row in batch["positions"]] == [position.id]


@pytest.mark.asyncio
async def test_force_approve_without_reason_in_body_is_rejected(client, session) -> None:
    """`force` без причины в теле — 400 с внятным текстом, а не тихий обход."""
    user = await _make_user(session, "gate-no-reason@test.local")
    plan, positions, _route = await _make_plan_with_positions(session, "FG-GATE-API-NOREASON", 1)
    product = await session.get(Product, positions[0].product_id)
    product.is_active = False
    await session.flush()

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/{positions[0].id}/approve?force=true",
        json={},
        headers=_auth_headers(user),
    )

    assert response.status_code == 400, response.text
    assert "причин" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reason_without_force_does_not_require_override(client, session) -> None:
    """Причина без форса — обычное утверждение: лишнее поле не ломает контракт."""
    user = await _make_user(session, "gate-reason-no-force@test.local")
    plan, positions, _route = await _make_plan_with_positions(session, "FG-GATE-API-REASON", 1)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/{positions[0].id}/approve",
        json={"reason": "заметка на будущее"},
        headers=_auth_headers(user),
    )

    assert response.status_code == 200, response.text
    assert response.json()["validation_status"] == "valid"


@pytest.mark.asyncio
async def test_auto_release_whole_plan_is_blocked_by_invalid_position(session) -> None:
    """Авто-выпуск всего плана (без явного списка) гейт тоже останавливает."""
    position = await _seed_position(
        session, sku="FG-GATE-AUTO", validation_status=PlanPositionValidationStatus.invalid
    )
    position.validation_errors = ["route_contains_excluded_step: DRILLING"]

    with pytest.raises(ValueError) as exc_info:
        await create_release_batch(session, production_plan_id=position.production_plan_id)

    assert str(position.id) in str(exc_info.value)


@pytest.mark.asyncio
async def test_released_position_is_not_touched_by_gate(session) -> None:
    """Позиции в статусе «выпущено» гейт не затрагивает: их статус не approved."""
    position = await _seed_position(
        session,
        sku="FG-GATE-RELEASED",
        validation_status=PlanPositionValidationStatus.invalid,
        position_status=PlanPositionStatus.released,
    )
    position.released_at = datetime.now(UTC)

    with pytest.raises(ValueError) as exc_info:
        await create_release_batch(
            session,
            production_plan_id=position.production_plan_id,
            positions=[{"plan_position_id": position.id, "release_quantity": "100"}],
        )

    # Отказ приходит от проверки «должна быть approved», а не от гейта валидации.
    assert "approved" in str(exc_info.value)
