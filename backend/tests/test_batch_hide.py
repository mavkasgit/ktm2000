"""«Убрать из списка» батча импорта плана: скрытие вместо физического удаления (#233, ADR-0056).

Смысл скрытия — в том, чего оно НЕ делает: не трогает позиции, задачи, передачи,
ledger, узел журнала действий и `AuditLog`, не меняет статус и не откатывает
применённый батч. Поэтому проверка не «после скрытия что-то пропало», а снимок
живых данных до и после + инварианты. Второй край — список: по умолчанию скрытых
нет, `include_hidden=true` их возвращает, а файл-источник не осиротевает, пока на
него ссылается скрытый батч.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action
from app.models.audit_log import AuditLog
from app.models.imports import ImportBatch, ImportBatchMode, ImportBatchStatus, ImportFile
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanChangeSetStatus,
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.transfer import Transfer
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from app.transfers.services import transfer_send
from tests.helpers.auth import user_headers
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_file(session: AsyncSession, tag: str) -> ImportFile:
    file = ImportFile(
        original_filename=f"{tag}.xlsx",
        stored_path=f"/tmp/{tag}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256=tag.ljust(64, "0")[:64],
        size_bytes=10,
    )
    session.add(file)
    await session.flush()
    return file


async def _make_plan(session: AsyncSession, tag: str) -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN-{tag}", name=f"Plan {tag}", status=ProductionPlanStatus.draft,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _make_batch(
    session: AsyncSession,
    plan: ProductionPlan,
    file: ImportFile,
    *,
    status: ImportBatchStatus = ImportBatchStatus.parsed,
) -> ImportBatch:
    batch = ImportBatch(
        source_file_id=file.id, production_plan_id=plan.id, mode=ImportBatchMode.create_plan,
        status=status, sheet_name="План", header_row_number=1, total_rows=1, parsed_rows=1, summary={},
    )
    session.add(batch)
    await session.flush()
    return batch


def _make_position(
    session: AsyncSession, plan: ProductionPlan, product: Product, batch: ImportBatch, *, row: int
) -> PlanPosition:
    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id, import_batch_id=batch.id,
        source_type=PlanSourceType.excel_import, source_sku=product.sku, source_name=product.name,
        quantity=Decimal("10"), source_payload={}, source_row_number=row,
        source_fingerprint=f"fp-{batch.id}-{row}", source_row_hash=f"hash-{batch.id}-{row}",
        status=PlanPositionStatus.draft, validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[], period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False,
    )
    session.add(pos)
    return pos


async def _make_change_set(
    session: AsyncSession, plan: ProductionPlan, batch: ImportBatch, positions: list[PlanPosition]
) -> PlanChangeSet:
    change_set = PlanChangeSet(
        production_plan_id=plan.id, import_batch_id=batch.id, status=PlanChangeSetStatus.applied,
    )
    session.add(change_set)
    await session.flush()
    session.add_all(
        [
            PlanChangeItem(
                change_set_id=change_set.id, plan_position_id=pos.id,
                change_action=PlanChangeAction.create_position,
                status=PlanChangeItemStatus.applied, before_data={}, after_data={},
            )
            for pos in positions
        ]
    )
    change_set.applied_at = datetime.now().astimezone()
    await session.flush()
    return change_set


async def _make_transfer_chain(
    session: AsyncSession, plan: ProductionPlan, product: Product, pos: PlanPosition, *, tag: str
) -> Transfer:
    """Живой downstream батча: линии → задачи → передача и её проводки."""
    user = User(username=f"{tag}-op", full_name=f"Operator {tag}", role=UserRole.operator)
    session.add(user)
    await session.flush()
    sec1 = Section(code=f"{tag}-S1", name="S1", type="laser", is_active=True, sort_order=1)
    sec2 = Section(code=f"{tag}-S2", name="S2", type="laser", is_active=True, sort_order=2)
    session.add_all([sec1, sec2])
    await session.flush()
    route = ProductionRoute(name=f"R-{tag}", is_active=True)
    session.add(route)
    await session.flush()
    st1 = RouteStage(route_id=route.id, sequence=1, section_id=sec1.id, is_final=False)
    st2 = RouteStage(route_id=route.id, sequence=2, section_id=sec2.id, is_final=True)
    session.add_all([st1, st2])
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()
    line1 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec1.id,
        product_id=product.id, route_id=route.id, route_stage_id=st1.id,
        sequence=1, planned_quantity=Decimal("10"),
    )
    line2 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec2.id,
        product_id=product.id, route_id=route.id, route_stage_id=st2.id,
        sequence=2, planned_quantity=Decimal("10"),
    )
    session.add_all([line1, line2])
    await session.flush()
    task1 = WorkTask(
        section_plan_line_id=line1.id, section_id=sec1.id, product_id=product.id,
        route_stage_id=st1.id, planned_quantity=Decimal("10"), status=WorkTaskStatus.ready,
    )
    task2 = WorkTask(
        section_plan_line_id=line2.id, section_id=sec2.id, product_id=product.id,
        route_stage_id=st2.id, planned_quantity=Decimal("10"), status=WorkTaskStatus.waiting_previous,
    )
    session.add_all([task1, task2])
    await session.flush()
    #: Материал должен лежать на участке-источнике с ТЕМ ЖЕ признаком операций,
    #: что уйдёт с передачей: `completed_operations` — часть ключа остатка
    #: (ADR-0055), и `[]` («операций не было») не равно NULL. Маршрут без
    #: RouteOperation — SEND несёт именно `[]`.
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product.id,
            from_location_id=None,
            to_location_id=sec1.id,
            quantity=Decimal("5"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
            completed_operations=[],
        ),
    )
    result = await transfer_send(
        session, from_task_id=task1.id, to_task_id=task2.id, quantity=Decimal("5"),
        actor_id=user.id, allow_over_plan=True,
    )
    transfer = await session.get(Transfer, result["transfer_id"])
    assert transfer is not None
    return transfer


async def _row_counts(session: AsyncSession) -> dict[str, int]:
    """Снимок живых данных: что скрытие обязано оставить как есть."""
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar() or 0

    return {
        "positions": await count(PlanPosition),
        "change_items": await count(PlanChangeItem),
        "change_sets": await count(PlanChangeSet),
        "section_plan_lines": await count(SectionPlanLine),
        "work_tasks": await count(WorkTask),
        "transfers": await count(Transfer),
        "stock_transactions": await count(StockTransaction),
        "actions": await count(Action),
        "audit_logs": await count(AuditLog),
    }


async def test_hide_keeps_everything_alive(session: AsyncSession, client) -> None:
    product = await _make_product(session, "HIDE-1")
    plan = await _make_plan(session, "HIDE-1")
    file = await _make_file(session, "hide-1")
    batch = await _make_batch(session, plan, file, status=ImportBatchStatus.applied)
    position = _make_position(session, plan, product, batch, row=2)
    await session.flush()
    await _make_change_set(session, plan, batch, [position])
    await _make_transfer_chain(session, plan, product, position, tag="HIDE-1")
    await session.commit()
    before = await _row_counts(session)
    assert before["positions"] == 1 and before["transfers"] == 1

    response = await client.post(f"/api/production-plans/{plan.id}/batches/{batch.id}/hide")

    assert response.status_code == 200, response.text
    assert response.json() == {"hidden": True, "batch_id": batch.id}
    assert await _row_counts(session) == before
    # Статус ортогонален скрытости: применённый батч остаётся применённым,
    # его позиции и файл живы — скрытие прячет строку, а не данные.
    await session.refresh(batch)
    assert batch.status == ImportBatchStatus.applied
    assert batch.deleted_at is not None
    assert (await session.get(ImportBatch, batch.id)) is not None
    assert (await session.get(ImportFile, file.id)) is not None
    await assert_no_invariants_violations(session, context="batch-hide")


async def test_hide_records_author_and_reason(session: AsyncSession, auth_client) -> None:
    plan = await _make_plan(session, "HIDE-2")
    file = await _make_file(session, "hide-2")
    batch = await _make_batch(session, plan, file)
    actor = (await session.execute(select(User).where(User.username == "testauth"))).scalar_one()
    await session.commit()

    response = await auth_client.post(
        f"/api/production-plans/{plan.id}/batches/{batch.id}/hide",
        json={"reason": "дубль загрузки"},
    )

    assert response.status_code == 200, response.text
    await session.refresh(batch)
    assert batch.delete_reason == "дубль загрузки"
    assert batch.deleted_by == actor.id


async def test_hide_is_idempotent(session: AsyncSession, client) -> None:
    plan = await _make_plan(session, "HIDE-3")
    file = await _make_file(session, "hide-3")
    batch = await _make_batch(session, plan, file)
    await session.commit()

    first = await client.post(f"/api/production-plans/{plan.id}/batches/{batch.id}/hide")
    assert first.status_code == 200, first.text
    await session.refresh(batch)
    hidden_at = batch.deleted_at

    second = await client.post(f"/api/production-plans/{plan.id}/batches/{batch.id}/hide")
    assert second.status_code == 200, second.text
    assert second.json() == {"hidden": True, "batch_id": batch.id}
    await session.refresh(batch)
    assert batch.deleted_at == hidden_at


async def test_hide_rejects_short_reason(session: AsyncSession, client) -> None:
    plan = await _make_plan(session, "HIDE-4")
    file = await _make_file(session, "hide-4")
    batch = await _make_batch(session, plan, file)
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/batches/{batch.id}/hide",
        json={"reason": "ну"},
    )

    assert response.status_code == 400, response.text
    await session.refresh(batch)
    assert batch.deleted_at is None


async def test_hide_rejects_foreign_plan_batch(session: AsyncSession, client) -> None:
    plan = await _make_plan(session, "HIDE-5")
    other = await _make_plan(session, "HIDE-5B")
    file = await _make_file(session, "hide-5")
    batch = await _make_batch(session, plan, file)
    await session.commit()

    response = await client.post(f"/api/production-plans/{other.id}/batches/{batch.id}/hide")

    assert response.status_code == 404, response.text
    await session.refresh(batch)
    assert batch.deleted_at is None


async def test_lists_exclude_hidden_by_default_and_show_with_flag(session: AsyncSession, client) -> None:
    plan = await _make_plan(session, "HIDE-6")
    file = await _make_file(session, "hide-6")
    hidden = await _make_batch(session, plan, file)
    visible = await _make_batch(session, plan, file)
    await session.commit()

    hidden_resp = await client.post(f"/api/production-plans/{plan.id}/batches/{hidden.id}/hide")
    assert hidden_resp.status_code == 200, hidden_resp.text

    plan_rows = (await client.get(f"/api/production-plans/{plan.id}/files")).json()
    all_rows = (await client.get("/api/production-plans/all-files")).json()
    assert [row["batch_id"] for row in plan_rows] == [visible.id]
    assert [row["batch_id"] for row in all_rows] == [visible.id]
    assert all(row["hidden"] is False for row in plan_rows + all_rows)

    plan_with_hidden = (
        await client.get(f"/api/production-plans/{plan.id}/files?include_hidden=true")
    ).json()
    all_with_hidden = (
        await client.get("/api/production-plans/all-files?include_hidden=true")
    ).json()
    assert sorted(row["batch_id"] for row in plan_with_hidden) == sorted([hidden.id, visible.id])
    assert sorted(row["batch_id"] for row in all_with_hidden) == sorted([hidden.id, visible.id])
    by_id = {row["batch_id"]: row for row in plan_with_hidden}
    # Скрытость ортогональна статусу: помечена скрытая строка, статус прежний,
    # и в include_hidden она просто возвращается на место.
    assert by_id[hidden.id]["hidden"] is True
    assert by_id[hidden.id]["status"] == ImportBatchStatus.parsed.value
    assert by_id[visible.id]["hidden"] is False


async def test_hidden_batch_keeps_file_of_deleted_sibling(session: AsyncSession, client) -> None:
    plan = await _make_plan(session, "HIDE-7")
    file = await _make_file(session, "hide-7")
    hidden = await _make_batch(session, plan, file)
    sibling = await _make_batch(session, plan, file)
    await session.commit()

    hide = await client.post(f"/api/production-plans/{plan.id}/batches/{hidden.id}/hide")
    assert hide.status_code == 200, hide.text
    delete = await client.delete(f"/api/production-plans/{plan.id}/batches/{sibling.id}")
    assert delete.status_code == 200, delete.text

    # Ссылка скрытого батча на файл жива: «Скачать» у него не должен сломаться.
    assert (await session.get(ImportFile, file.id)) is not None
    assert (await session.get(ImportBatch, hidden.id)) is not None


async def test_physically_deleted_batch_takes_its_last_file(session: AsyncSession, client) -> None:
    """Обратный край: без живых батчей файл-источник удаляется вместе с ними."""
    plan = await _make_plan(session, "HIDE-8")
    file = await _make_file(session, "hide-8")
    batch = await _make_batch(session, plan, file)
    await session.commit()

    delete = await client.delete(f"/api/production-plans/{plan.id}/batches/{batch.id}")

    assert delete.status_code == 200, delete.text
    assert (await session.get(ImportFile, file.id)) is None


@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.transporter, UserRole.operator])
async def test_hide_is_admin_only(session: AsyncSession, client, role: UserRole) -> None:
    """Скрытие — мутация реестра импортов, как apply/rollback/DELETE батча.

    Право ровно то же, что у соседних ручек (ADR-0057): историю может читать
    любой читатель, а убрать из неё строку — admin. Иначе «убрать из списка»
    оказалось бы доступнее, чем «удалить».
    """
    plan = await _make_plan(session, "HIDE-9")
    file = await _make_file(session, "hide-9")
    batch = await _make_batch(session, plan, file)
    _, headers = await user_headers(session, role, f"hider_{role.value}")

    response = await client.post(
        f"/api/production-plans/{plan.id}/batches/{batch.id}/hide", headers=headers
    )

    assert response.status_code == 403, response.text
    await session.refresh(batch)
    assert batch.deleted_at is None
