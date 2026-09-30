"""Tests for GET /api/transfers/history pagination (offset, limit, total)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.section import Section
from app.models.spg import StorageProductionGroup
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.stock import Reason, StockCommand, StockCommandService
from app.stock.services import StockProjectionManager
from tests.stock.test_transfer_stage2 import _make_tasks_transferable, _make_two_ghp_setup
from tests.test_integrity_invariants import _release_via_take_to_work


async def _make_tasks_transferable_reuse_stock(session, client, setup: dict) -> dict:
    """Like stage-2 helper, but reuses the shared stock section across setups."""
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert len(tasks) >= 2
    src = tasks[-2]
    dst = tasks[-1]

    stock = (
        await session.execute(select(Section).where(Section.code == "T2-STK"))
    ).scalar_one_or_none()
    if stock is None:
        stock = Section(code="T2-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
        session.add(stock)
        await session.flush()

    # Признак берём у того же источника, что и плановое ``TRANSFER_RECEIVE``
    # (ADR-0043 §2): иначе приход лёг бы в NULL-группу, а receive искал бы
    # группу маршрута задания и получал «available 0» (ADR-0055).
    from app.services.material_operations import completed_operations_for_task

    ops = await completed_operations_for_task(session, src)
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=src.product_id,
            from_location_id=None,
            to_location_id=stock.id,
            quantity=src.planned_quantity,
            reason=Reason.MANUAL_IN,
            completed_operations=ops,
            created_by=setup["user"].id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=src.product_id,
            from_location_id=stock.id,
            to_location_id=src.section_id,
            quantity=src.planned_quantity,
            reason=Reason.TRANSFER_RECEIVE,
            task_id=src.id,
            created_by=setup["user"].id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=src.product_id,
            from_location_id=src.section_id,
            to_location_id=src.section_id,
            quantity=src.planned_quantity,
            reason=Reason.COMPLETE,
            task_id=src.id,
            source_ref="test_seed",
            created_by=setup["user"].id,
        ),
    )
    await session.flush()

    pm = StockProjectionManager()
    cache = await pm.get_task_cache(session, src.id)
    assert cache["completed_quantity"] >= Decimal("0")

    return {"from_task_id": src.id, "to_task_id": dst.id, "user": setup["user"]}


async def _seed_transfer_records(
    session,
    setup: dict,
    ctx: dict,
    count: int,
    *,
    status: TransferStatus = TransferStatus.sent,
    comment: str | None = None,
    transfer_no_prefix: str | None = None,
    start_offset: int = 0,
) -> list[int]:
    """Insert transfer rows wired to the two-section setup from transfer stage-2 tests."""
    sec1, sec2 = setup["sections"]
    base_time = datetime.now(UTC)
    transfer_ids: list[int] = []
    prefix = transfer_no_prefix or f"HIST-{setup['product'].sku}"

    for i in range(count):
        offset_seconds = start_offset + i
        transfer = Transfer(
            transfer_no=f"{prefix}-{i:04d}",
            from_task_id=ctx["from_task_id"],
            to_task_id=ctx["to_task_id"],
            from_section_id=sec1.id,
            to_section_id=sec2.id,
            product_id=setup["product"].id,
            sent_quantity=Decimal("1"),
            status=status,
            sent_by=ctx["user"].id,
            sent_at=base_time - timedelta(seconds=offset_seconds),
            created_at=base_time - timedelta(seconds=offset_seconds),
            comment=comment,
        )
        session.add(transfer)
        await session.flush()
        transfer_ids.append(transfer.id)

    await session.commit()
    return transfer_ids


@pytest.mark.asyncio
async def test_history_empty_total_zero(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    response = await client.get("/api/transfers/history")
    assert response.status_code == 200
    body = response.json()
    assert body["transfers"] == []
    assert body["total"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_history_offset_limit_pagination(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-PG")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=65)

    first_page = await client.get("/api/transfers/history?limit=50&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["transfers"]) == 50
    assert first_body["total"] == 65
    assert first_body["limit"] == 50
    assert first_body["offset"] == 0

    second_page = await client.get("/api/transfers/history?limit=50&offset=50")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["transfers"]) == 15
    assert second_body["total"] == 65
    assert second_body["limit"] == 50
    assert second_body["offset"] == 50

    first_ids = {item["transfer_id"] for item in first_body["transfers"]}
    second_ids = {item["transfer_id"] for item in second_body["transfers"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_history_spg_filter_total(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-SPG")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=8)

    spg_a = (
        await session.execute(
            select(StorageProductionGroup).where(StorageProductionGroup.code == "HIST-SPG-A")
        )
    ).scalar_one()

    empty_spg = StorageProductionGroup(code="HIST-SPG-EMPTY", name="Empty", is_active=True, sort_order=99)
    session.add(empty_spg)
    await session.commit()

    all_response = await client.get("/api/transfers/history")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 8

    spg_response = await client.get(f"/api/transfers/history?spg_id={spg_a.id}")
    assert spg_response.status_code == 200
    spg_body = spg_response.json()
    assert spg_body["total"] == 8
    assert len(spg_body["transfers"]) == 8
    assert spg_body["spg_id"] == spg_a.id

    empty_response = await client.get(f"/api/transfers/history?spg_id={empty_spg.id}")
    assert empty_response.status_code == 200
    empty_body = empty_response.json()
    assert empty_body["total"] == 0
    assert empty_body["transfers"] == []


@pytest.mark.asyncio
async def test_history_search_finds_across_pages(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-SRCH")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=64, start_offset=0)
    await _seed_transfer_records(
        session,
        setup,
        ctx,
        count=1,
        comment="UNIQUE-ZEBRA-SEARCH-MARKER",
        transfer_no_prefix="HIST-ZEBRA",
        start_offset=200,
    )

    first_page = await client.get("/api/transfers/history?limit=50&offset=0")
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert all(
        item.get("comment") != "UNIQUE-ZEBRA-SEARCH-MARKER"
        for item in first_body["transfers"]
    )

    second_page = await client.get("/api/transfers/history?limit=50&offset=50")
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert second_body["total"] == 65
    assert len(second_body["transfers"]) == 15
    assert any(
        item.get("comment") == "UNIQUE-ZEBRA-SEARCH-MARKER"
        for item in second_body["transfers"]
    )

    search_response = await client.get("/api/transfers/history?search=UNIQUE-ZEBRA-SEARCH-MARKER")
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["total"] >= 1
    assert any(
        item.get("comment") == "UNIQUE-ZEBRA-SEARCH-MARKER"
        for item in search_body["transfers"]
    )


@pytest.mark.asyncio
async def test_history_sort_by_sku(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    skus = ["CCC-HIST", "AAA-HIST", "MMM-HIST"]
    for index, sku in enumerate(skus):
        setup = await _make_two_ghp_setup(session, sku=sku)
        if index == 0:
            ctx = await _make_tasks_transferable(session, client, setup)
        else:
            ctx = await _make_tasks_transferable_reuse_stock(session, client, setup)
        await _seed_transfer_records(session, setup, ctx, count=1, transfer_no_prefix=f"HIST-{sku}")

    asc_response = await client.get("/api/transfers/history?sort=sku:asc&limit=50")
    assert asc_response.status_code == 200
    asc_body = asc_response.json()
    assert asc_body["total"] == 3
    asc_skus = [item["product_sku"] for item in asc_body["transfers"]]
    assert asc_skus == ["AAA-HIST", "CCC-HIST", "MMM-HIST"]

    desc_response = await client.get("/api/transfers/history?sort=product_sku:desc&limit=50")
    assert desc_response.status_code == 200
    desc_body = desc_response.json()
    desc_skus = [item["product_sku"] for item in desc_body["transfers"]]
    assert desc_skus == ["MMM-HIST", "CCC-HIST", "AAA-HIST"]


@pytest.mark.asyncio
async def test_history_status_filter(client, session) -> None:
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-STAT")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=4, status=TransferStatus.sent)
    await _seed_transfer_records(
        session,
        setup,
        ctx,
        count=2,
        status=TransferStatus.cancelled,
        transfer_no_prefix="HIST-CANCEL",
    )

    all_response = await client.get("/api/transfers/history?limit=50")
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 6

    sent_response = await client.get("/api/transfers/history?status=sent&limit=50")
    assert sent_response.status_code == 200
    sent_body = sent_response.json()
    assert sent_body["total"] == 4
    assert all(item["status"] == "sent" for item in sent_body["transfers"])

    cancelled_response = await client.get("/api/transfers/history?status=cancelled&limit=50")
    assert cancelled_response.status_code == 200
    cancelled_body = cancelled_response.json()
    assert cancelled_body["total"] == 2
    assert all(item["status"] == "cancelled" for item in cancelled_body["transfers"])


@pytest.mark.asyncio
async def test_history_multi_sort_sku_then_quantity(client, session) -> None:
    """Вторая колонка ?sort= раскладывает передачи одного SKU по количеству."""
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-MSORT")
    ctx = await _make_tasks_transferable(session, client, setup)
    transfer_ids = await _seed_transfer_records(
        session, setup, ctx, count=3, transfer_no_prefix="HIST-MS",
    )
    # Один SKU на все передачи: различаются только количества, причём в порядке,
    # обратном порядку их создания (tiebreaker по id).
    for transfer_id, qty in zip(transfer_ids, ("1", "3", "2"), strict=True):
        transfer = await session.get(Transfer, transfer_id)
        transfer.sent_quantity = Decimal(qty)
    await session.commit()

    single = await client.get("/api/transfers/history?sort=sku:asc&limit=50")
    multi = await client.get(
        "/api/transfers/history?sort=sku:asc,quantity:desc&limit=50",
    )
    assert single.status_code == 200, single.text
    assert multi.status_code == 200, multi.text

    single_ids = [item["transfer_id"] for item in single.json()["transfers"]]
    multi_ids = [item["transfer_id"] for item in multi.json()["transfers"]]
    assert single_ids == transfer_ids
    assert multi_ids == [transfer_ids[1], transfer_ids[2], transfer_ids[0]]
    assert [
        item["sent_quantity"] for item in multi.json()["transfers"]
    ] == ["3", "2", "1"]


@pytest.mark.asyncio
async def test_history_keeps_short_field_aliases(client, session) -> None:
    """Короткие имена sku/from/to/quantity — рабочие синонимы длинных колонок."""
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    set_a = await _make_two_ghp_setup(session, sku="AAA-SHORT")
    ctx_a = await _make_tasks_transferable(session, client, set_a)
    set_b = await _make_two_ghp_setup(session, sku="BBB-SHORT")
    ctx_b = await _make_tasks_transferable_reuse_stock(session, client, set_b)

    # Имена секций у фикстур одинаковые ("S1"/"S2") — переименовываем, иначе
    # сортировка по участкам была бы вырожденной.
    for setup, prefix in ((set_a, "AAA"), (set_b, "BBB")):
        setup["sections"][0].name = f"{prefix}-FROM"
        setup["sections"][1].name = f"{prefix}-TO"
    await session.commit()

    ids_a = await _seed_transfer_records(
        session, set_a, ctx_a, count=2, transfer_no_prefix="HIST-AAA",
    )
    ids_b = await _seed_transfer_records(
        session, set_b, ctx_b, count=2, transfer_no_prefix="HIST-BBB",
    )
    for transfer_id, qty in zip(
        [*ids_a, *ids_b], ("4", "1", "3", "2"), strict=True,
    ):
        transfer = await session.get(Transfer, transfer_id)
        transfer.sent_quantity = Decimal(qty)
    await session.commit()

    async def _order(sort: str, key: str) -> list[str]:
        resp = await client.get(f"/api/transfers/history?sort={sort}&limit=50")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4
        return [item[key] for item in body["transfers"]]

    # Каждый короткий алиас даёт тот же порядок, что и его длинная колонка.
    assert await _order("sku:asc", "transfer_id") == await _order(
        "product_sku:asc", "transfer_id",
    )
    assert await _order("from:asc", "from_section_name") == await _order(
        "from_section_name:asc", "from_section_name",
    )
    assert await _order("to:asc", "to_section_name") == await _order(
        "to_section_name:asc", "to_section_name",
    )
    assert await _order("quantity:desc", "sent_quantity") == await _order(
        "sent_quantity:desc", "sent_quantity",
    )

    # Порядки не вырожденные: все четыре колонки реально различают строки.
    assert await _order("sku:asc", "product_sku") == [
        "AAA-SHORT", "AAA-SHORT", "BBB-SHORT", "BBB-SHORT",
    ]
    assert await _order("from:asc", "from_section_name") == [
        "AAA-FROM", "AAA-FROM", "BBB-FROM", "BBB-FROM",
    ]
    assert await _order("to:asc", "to_section_name") == [
        "AAA-TO", "AAA-TO", "BBB-TO", "BBB-TO",
    ]
    assert await _order("quantity:desc", "sent_quantity") == ["4", "3", "2", "1"]


@pytest.mark.asyncio
async def test_history_default_order_is_created_at_desc(client, session) -> None:
    """Без параметра сортировки журнал: новые сверху (не по id)."""
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-DEF")
    ctx = await _make_tasks_transferable(session, client, setup)
    transfer_ids = await _seed_transfer_records(
        session, setup, ctx, count=3, transfer_no_prefix="HIST-DEF",
    )

    # created_at намеренно НЕ совпадает с порядком id: последняя по id передача
    # оказывается самой старой, поэтому «desc по id» и «desc по created_at»
    # дают разные последовательности.
    base = datetime.now(UTC)
    for transfer_id, created_at in zip(
        transfer_ids,
        (base - timedelta(hours=2), base - timedelta(hours=1), base - timedelta(hours=3)),
        strict=True,
    ):
        transfer = await session.get(Transfer, transfer_id)
        transfer.created_at = created_at
    await session.commit()

    resp = await client.get("/api/transfers/history?limit=50")
    assert resp.status_code == 200, resp.text
    assert [item["transfer_id"] for item in resp.json()["transfers"]] == [
        transfer_ids[1],
        transfer_ids[0],
        transfer_ids[2],
    ]


@pytest.mark.asyncio
async def test_history_rejects_unknown_sort_field(client, session) -> None:
    """Неизвестное поле сортировки — 400, а не пустой журнал."""
    setup = await _make_two_ghp_setup(session, sku="HIST-400")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=1, transfer_no_prefix="HIST-400")

    resp = await client.get("/api/transfers/history?sort=unknown:asc")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_history_rejects_unknown_direction(client, session) -> None:
    """Направление вне asc/desc — 400."""
    setup = await _make_two_ghp_setup(session, sku="HIST-400B")
    ctx = await _make_tasks_transferable(session, client, setup)
    await _seed_transfer_records(session, setup, ctx, count=1, transfer_no_prefix="HIST-400B")

    resp = await client.get("/api/transfers/history?sort=quantity:sideways")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_history_ignores_legacy_sort_by_params(client, session) -> None:
    """Сепарактные sort_by/sort_order больше не объявлены и не сортируют."""
    await session.execute(Transfer.__table__.delete())
    await session.commit()

    setup = await _make_two_ghp_setup(session, sku="HIST-LEG")
    ctx = await _make_tasks_transferable(session, client, setup)
    transfer_ids = await _seed_transfer_records(
        session, setup, ctx, count=3, transfer_no_prefix="HIST-LEG",
    )
    # Переворачиваем время создания относительно номеров передач: дефолтный
    # порядок журнала (created_at:desc) и «номер по возрастанию» расходятся.
    base = datetime.now(UTC)
    for transfer_id, created_at in zip(
        transfer_ids,
        (base - timedelta(hours=3), base - timedelta(hours=2), base - timedelta(hours=1)),
        strict=True,
    ):
        transfer = await session.get(Transfer, transfer_id)
        transfer.created_at = created_at
    await session.commit()

    legacy = await client.get(
        "/api/transfers/history?sort_by=transfer_no&sort_order=asc&limit=50",
    )
    assert legacy.status_code == 200, legacy.text
    assert [item["transfer_id"] for item in legacy.json()["transfers"]] == list(
        reversed(transfer_ids),
    )

    # «По номеру передачи возрастанию» — прямой порядок: значит подставленные
    # legacy-поля проявились бы, если бы сервер их читал.
    by_no = await client.get(
        "/api/transfers/history?sort=transfer_no:asc&limit=50",
    )
    assert by_no.status_code == 200, by_no.text
    assert [item["transfer_id"] for item in by_no.json()["transfers"]] == transfer_ids