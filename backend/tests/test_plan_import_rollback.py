"""Импорт плана: применение/откат батча и повторное применение после отката (#172).

Наблюдаемый контракт:
- apply проставляет ``applied_at`` сета и отдаёт его в ``GET /production-plans/{id}/files``;
- rollback очищает ``applied_at``, переводит сет/батч в ``cancelled``, возвращает строки
  в применимое состояние, а позиции уходят из превью;
- повторный apply откаченного сета переиспользует свою отменённую позицию
  (уникальная пара ``import_batch_id`` + ``source_row_number``), а не создаёт дубль;
- released-позиция блокирует откат (400), сет остаётся ``applied``;
- ``applied_at`` фиксирует порядок применения, а не порядок загрузки файлов — по нему
  фронт выбирает последний применённый батч для LIFO-отката.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imports import ImportBatch, ImportBatchMode, ImportBatchStatus, ImportFile
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanChangeSetStatus,
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()
    return product


async def _make_plan(session: AsyncSession, tag: str) -> ProductionPlan:
    plan = ProductionPlan(plan_no=f"PLAN-{tag}", name=f"Plan {tag}", status=ProductionPlanStatus.draft)
    session.add(plan)
    await session.flush()
    return plan


async def _make_batch(session: AsyncSession, plan: ProductionPlan, tag: str) -> ImportBatch:
    file = ImportFile(
        original_filename=f"{tag}.xlsx",
        stored_path=f"/tmp/{tag}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        detected_format="zip-workbook",
        file_sha256=f"{tag:<64}"[:64].replace(" ", "0"),
        size_bytes=10,
    )
    session.add(file)
    await session.flush()
    batch = ImportBatch(
        source_file_id=file.id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="План",
        header_row_number=1,
        total_rows=2,
        parsed_rows=1,
        summary={},
    )
    session.add(batch)
    await session.flush()
    return batch


async def _add_create_item(
    session: AsyncSession,
    change_set: PlanChangeSet,
    batch: ImportBatch,
    product: Product,
    row: int,
) -> PlanChangeItem:
    item = PlanChangeItem(
        change_set_id=change_set.id,
        source_row_number=row,
        source_ref=f"rows:{row}",
        change_action=PlanChangeAction.create_position,
        before_data=None,
        after_data={
            "product_id": product.id,
            "source_sku": product.sku,
            "source_name": product.name,
            "quantity": "100",
            "source_ref": f"rows:{row}",
            "source_row_numbers": [row],
            "source_fingerprint": f"fp-{batch.id}-{row}",
            "source_row_hash": f"hash-{batch.id}-{row}",
            "source_payload": {"period_start": "2026-05-01", "period_end": "2026-05-31"},
        },
        status=PlanChangeItemStatus.pending,
        warnings=[],
        errors=[],
    )
    session.add(item)
    await session.flush()
    return item


async def _make_change_set(
    session: AsyncSession,
    plan: ProductionPlan,
    batch: ImportBatch,
    product: Product,
    row: int,
) -> tuple[PlanChangeSet, PlanChangeItem]:
    change_set = PlanChangeSet(production_plan_id=plan.id, import_batch_id=batch.id, summary={})
    session.add(change_set)
    await session.flush()
    item = await _add_create_item(session, change_set, batch, product, row)
    return change_set, item


async def _apply(client, plan_id: int, change_set_id: int) -> dict:
    response = await client.post(f"/api/production-plans/{plan_id}/change-sets/{change_set_id}/apply")
    assert response.status_code == 200, response.text
    return response.json()


async def _rollback(client, plan_id: int, change_set_id: int):
    return await client.post(f"/api/production-plans/{plan_id}/change-sets/{change_set_id}/rollback")


async def _files_by_batch(client, plan_id: int) -> dict[int, dict]:
    response = await client.get(f"/api/production-plans/{plan_id}/files")
    assert response.status_code == 200, response.text
    return {row["batch_id"]: row for row in response.json()}


async def _preview(client, plan_id: int) -> dict:
    response = await client.get(f"/api/production-plans/{plan_id}/preview")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_apply_sets_applied_at_and_change_set_link_in_files(client, session) -> None:
    """apply заполняет applied_at и связывает батч с применённым сетом в списке файлов."""
    product = await _make_product(session, "ROLL-APPLY")
    plan = await _make_plan(session, "ROLL-APPLY")
    batch = await _make_batch(session, plan, "ROLL-APPLY")
    change_set, _ = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    body = await _apply(client, plan.id, change_set.id)
    assert body["created_positions"] == 1

    info = (await _files_by_batch(client, plan.id))[batch.id]
    assert info["change_set_id"] == change_set.id
    assert info["production_plan_id"] == plan.id
    assert info["status"] == "applied"
    assert info["applied_at"] is not None


@pytest.mark.asyncio
async def test_second_apply_of_applied_change_set_adds_nothing_and_keeps_applied_at(client, session) -> None:
    """Повторный apply уже применённого сета не создаёт позиций и не переписывает applied_at."""
    product = await _make_product(session, "ROLL-IDEMPOTENT")
    plan = await _make_plan(session, "ROLL-IDEMPOTENT")
    batch = await _make_batch(session, plan, "ROLL-IDEMPOTENT")
    change_set, _ = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    first = await _apply(client, plan.id, change_set.id)
    assert first["created_positions"] == 1
    applied_at_before = (await _files_by_batch(client, plan.id))[batch.id]["applied_at"]
    assert applied_at_before is not None

    # Сет уже applied: раннее возвращение отдаёт превью без агрегатов применения.
    second = await _apply(client, plan.id, change_set.id)
    assert "created_positions" not in second
    assert second["positions_total"] == 1

    active = (
        await session.execute(
            select(PlanPosition).where(
                PlanPosition.import_batch_id == batch.id,
                PlanPosition.source_row_number == 6,
                PlanPosition.status != PlanPositionStatus.cancelled,
            )
        )
    ).scalars().all()
    assert len(active) == 1

    await session.refresh(change_set)
    assert change_set.status == PlanChangeSetStatus.applied
    assert (await _files_by_batch(client, plan.id))[batch.id]["applied_at"] == applied_at_before


@pytest.mark.asyncio
async def test_rollback_clears_applied_at_and_restores_applicable_state(client, session) -> None:
    """rollback снимает applied_at, отменяет сет/батч и возвращает строку в pending."""
    product = await _make_product(session, "ROLL-CLEAR")
    plan = await _make_plan(session, "ROLL-CLEAR")
    batch = await _make_batch(session, plan, "ROLL-CLEAR")
    change_set, item = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    assert (await _apply(client, plan.id, change_set.id))["created_positions"] == 1

    response = await _rollback(client, plan.id, change_set.id)
    assert response.status_code == 200, response.text

    info = (await _files_by_batch(client, plan.id))[batch.id]
    assert info["applied_at"] is None
    assert info["status"] == "cancelled"

    await session.refresh(change_set)
    assert change_set.status == PlanChangeSetStatus.cancelled
    assert change_set.applied_at is None

    # Строка снова pending (правило plan_import_row_status) — иначе повторный apply
    # молча пропустит её как уже применённую.
    await session.refresh(item)
    assert item.status == PlanChangeItemStatus.pending

    assert (await _preview(client, plan.id))["positions_total"] == 0


@pytest.mark.asyncio
async def test_reapply_after_rollback_reuses_position_without_duplicate_row(client, session) -> None:
    """Повторный apply откаченного сета создаёт позицию ещё раз, но без дубля строки."""
    product = await _make_product(session, "ROLL-REAPPLY")
    plan = await _make_plan(session, "ROLL-REAPPLY")
    batch = await _make_batch(session, plan, "ROLL-REAPPLY")
    change_set, _ = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    assert (await _apply(client, plan.id, change_set.id))["created_positions"] == 1

    rollback_response = await _rollback(client, plan.id, change_set.id)
    assert rollback_response.status_code == 200, rollback_response.text
    assert rollback_response.json()["positions_total"] == 0

    second = await _apply(client, plan.id, change_set.id)
    assert second["created_positions"] == 1
    assert (await _preview(client, plan.id))["positions_total"] == 1

    active = (
        await session.execute(
            select(PlanPosition).where(
                PlanPosition.production_plan_id == plan.id,
                PlanPosition.status != PlanPositionStatus.cancelled,
            )
        )
    ).scalars().all()
    assert len(active) == 1
    assert active[0].import_batch_id == batch.id
    assert active[0].source_row_number == 6

    info = (await _files_by_batch(client, plan.id))[batch.id]
    assert info["status"] == "applied"
    assert info["applied_at"] is not None


@pytest.mark.asyncio
async def test_reapply_after_legacy_rollback_recovers_items_left_applied(client, session) -> None:
    """Сет, откаченный до #172 (строки остались applied), применяется повторно, а не молчит."""
    product = await _make_product(session, "ROLL-LEGACY")
    plan = await _make_plan(session, "ROLL-LEGACY")
    batch = await _make_batch(session, plan, "ROLL-LEGACY")
    change_set, item = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    body = await _apply(client, plan.id, change_set.id)
    assert body["created_positions"] == 1
    position = await session.get(PlanPosition, body["positions"][0]["id"])

    # Легаси-состояние: сет/батч/позиция отменены, но строку сета прежний откат
    # оставлял `applied` — её и должен вернуть в применимое состояние apply.
    change_set.status = PlanChangeSetStatus.cancelled
    change_set.applied_at = None
    batch.status = ImportBatchStatus.cancelled
    position.status = PlanPositionStatus.cancelled
    await session.commit()
    await session.refresh(item)
    assert item.status == PlanChangeItemStatus.applied

    second = await _apply(client, plan.id, change_set.id)
    assert second["created_positions"] == 1

    preview = await _preview(client, plan.id)
    assert preview["positions_total"] == 1
    assert preview["positions"][0]["id"] == position.id

    info = (await _files_by_batch(client, plan.id))[batch.id]
    assert info["status"] == "applied"
    assert info["applied_at"] is not None


@pytest.mark.asyncio
async def test_rollback_released_position_returns_400_and_keeps_change_set_applied(client, session) -> None:
    """Откат сета с released-позицией запрещён и не отменяет применённый сет."""
    product = await _make_product(session, "ROLL-RELEASED")
    plan = await _make_plan(session, "ROLL-RELEASED")
    batch = await _make_batch(session, plan, "ROLL-RELEASED")
    change_set, _ = await _make_change_set(session, plan, batch, product, row=6)
    await session.commit()

    body = await _apply(client, plan.id, change_set.id)
    position = await session.get(PlanPosition, body["positions"][0]["id"])
    position.status = PlanPositionStatus.released
    await session.commit()

    response = await _rollback(client, plan.id, change_set.id)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Cannot rollback: position already released"

    info = (await _files_by_batch(client, plan.id))[batch.id]
    assert info["status"] == "applied"
    assert info["applied_at"] is not None

    await session.refresh(change_set)
    assert change_set.status == PlanChangeSetStatus.applied
    assert change_set.applied_at is not None


@pytest.mark.asyncio
async def test_applied_at_follows_apply_order_not_upload_order(client, session) -> None:
    """applied_at отражает порядок применения, а не порядок загрузки батчей."""
    product = await _make_product(session, "ROLL-ORDER")
    plan = await _make_plan(session, "ROLL-ORDER")
    batch_first = await _make_batch(session, plan, "ROLL-ORDER-1")
    batch_second = await _make_batch(session, plan, "ROLL-ORDER-2")
    cs_first, _ = await _make_change_set(session, plan, batch_first, product, row=6)
    cs_second, _ = await _make_change_set(session, plan, batch_second, product, row=7)
    await session.commit()

    # Применяем в обратном порядке загрузки: сначала второй батч, затем первый.
    assert (await _apply(client, plan.id, cs_second.id))["created_positions"] == 1
    assert (await _apply(client, plan.id, cs_first.id))["created_positions"] == 1

    files = await _files_by_batch(client, plan.id)
    applied_second = files[batch_second.id]["applied_at"]
    applied_first = files[batch_first.id]["applied_at"]
    assert applied_second is not None
    assert applied_first is not None
    assert datetime.fromisoformat(applied_first) > datetime.fromisoformat(applied_second)

    # Последний применённый батч (загруженный первым) — максимум applied_at:
    # именно его фронт выбирает для LIFO-отката.
    last_applied = max(files.values(), key=lambda info: datetime.fromisoformat(info["applied_at"]))
    assert last_applied["batch_id"] == batch_first.id
    assert last_applied["change_set_id"] == cs_first.id
