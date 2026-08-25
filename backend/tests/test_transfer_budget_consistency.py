"""E2E (тикет #107): ready-list и write guard согласуются на transferable.

Регрессионный тест против formula drift между read-path
(``GET /api/transfers/ready`` → ``app.transfers.queries.list_ready_to_transfer``)
и write-path (``app.transfers.services._get_task_transferable``): для одного и
того же сценария оба источника возвращают один и тот же transferable.

Три пути бюджета (тикет #106, ``app.transfers.budget``):
1. **plain** — ``remaining_plain(completed, transferred)``: `received` больше
   НЕ участвует (T6). completed=5, received=10, transferred=2 → **3**.
2. **transform** — ``build_outputs_progress`` + ``remaining_transform``:
   строка выхода резки по (задача, размер), produced и transferred.
3. **stock** — ``compute_stock_section_transferable`` (→ ``remaining_stock``):
   складская строка (section_plan_line_id) по плану и физическому остатку.

Сценарии построены на существующих helpers: обычные production-задачи не на
финальном этапе, трансформирующая задача с выходами, stock-секции.

Тикет #119: оракул расширен до трёхсторонней сверки
write-guard ≡ read-SQL (фабрики ``app.transfers.budget`` поверх
ledger-подзапросов) ≡ чистые Decimal-функции — включая финальный участок,
где смысл бюджета — отправка (``remaining_send``, FINAL_RELEASE).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.models.user import User
from app.models.work_task import WorkTask
from app.stock import Reason, StockCommand, StockCommandService
from app.transfers.services import transfer_send

from tests.stock.test_transfer_stage2 import _make_two_ghp_setup
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    _release_via_take_to_work,
    assert_no_invariants_violations,
)
from tests.test_transfer_dimensions import (
    _complete_saw,
    _make_dim_route_fixture,
    _make_transform_route_fixture,
    _seed_balance,
    _tasks_for_position,
)

pytestmark = pytest.mark.asyncio

_UNSET = object()


# ─── helpers ────────────────────────────────────────────────────────────────


async def _read_sql_budgets(session: AsyncSession, task: WorkTask) -> dict[str, Decimal]:
    """Read-SQL путь бюджета: фабрики ``app.transfers.budget`` поверх
    ledger-подзапросов (``net_*_sq``) для одной задачи — та же сборка,
    что в ready-запросе, но без скрытых копий формулы."""
    from app.stock.ledger import net_by_reason_sq, net_transferred_sq
    from app.stock.models import Reason
    from app.transfers.budget import sendable_qty_sql, transferable_qty_sql
    from app.transfers.queries import _completed_qty_subquery

    completed_sq = _completed_qty_subquery()
    transferred_sq = net_transferred_sq(alias="oracle_transferred_sq")
    released_sq = net_by_reason_sq(Reason.FINAL_RELEASE, alias="oracle_released_sq")
    completed_col = func.coalesce(completed_sq.c.completed_qty, 0)
    stmt = (
        select(
            transferable_qty_sql(
                completed_col,
                func.coalesce(transferred_sq.c.net_quantity, 0),
            ).label("transferable_qty"),
            sendable_qty_sql(
                completed_col,
                func.coalesce(released_sq.c.net_quantity, 0),
            ).label("sendable_qty"),
        )
        .outerjoin(transferred_sq, transferred_sq.c.task_id == task.id)
        .outerjoin(released_sq, released_sq.c.task_id == task.id)
        .where(completed_sq.c.task_id == task.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return {"transferable": Decimal("0"), "sendable": Decimal("0")}
    return {"transferable": row.transferable_qty, "sendable": row.sendable_qty}


async def _task_transferable(
    session: AsyncSession,
    task: WorkTask,
    dims: dict | None = None,
) -> Decimal:
    """Write guard: ``_get_task_transferable`` (тест_transfer_dimensions.py:774-779)."""
    from app.transfers.services import _get_task_transferable

    return await _get_task_transferable(session, task, dimensions=dims)


async def _ready_row(
    client,
    user: User,
    section_id: int,
    *,
    task_id: int | None = None,
    dims: object = _UNSET,
) -> dict:
    """Ровно одна ready-строка ``/api/transfers/ready`` по (задача, размер).

    ``dims=_UNSET`` — без фильтра по габариту; ``dims=None`` — искать
    безразмерную строку (габарит равен NULL).
    """
    resp = await client.get(
        f"/api/transfers/ready?section_id={section_id}", headers=_auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    matches = [
        item
        for item in items
        if (task_id is None or item["task_id"] == task_id)
        and (dims is _UNSET or item.get("dimensions") == dims)
    ]
    assert len(matches) == 1, f"ожидал ровно одну ready-строку, получил: {items}"
    return matches[0]


# ─── 1. plain: received не участвует в бюджете ───────────────────────────────


async def test_plain_ready_list_and_write_guard_agree_on_transferable(
    client, session
) -> None:
    """plain: completed=5, received=10, transferred=2 → ready-list и guard = 3.

    Ключевой сценарий тикета #107: доказывает, что ``received`` (10) больше не
    участвует в plain-бюджете (T6) — при старой формуле
    (``completed + received − transferred``) было бы 13.
    """
    setup = await _make_two_ghp_setup(session, sku="TBCPLN", qty=Decimal("10"))
    user = setup["user"]
    sec1 = setup["sections"][0]
    sec2 = setup["sections"][1]
    await _release_via_take_to_work(client, setup["position"].id)

    from_task = (
        await session.execute(select(WorkTask).where(WorkTask.section_id == sec1.id))
    ).scalar_one()
    to_task = (
        await session.execute(select(WorkTask).where(WorkTask.section_id == sec2.id))
    ).scalar_one()

    # received=10: входящая передача (материал выдан на участок), произведено 5.
    stock = Section(
        code="TBCPLN-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0
    )
    session.add(stock)
    await session.flush()
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=None,
            to_location_id=stock.id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=stock.id,
            to_location_id=from_task.section_id,
            quantity=Decimal("10"),
            reason=Reason.TRANSFER_RECEIVE,
            task_id=from_task.id,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=from_task.section_id,
            to_location_id=from_task.section_id,
            quantity=Decimal("5"),
            reason=Reason.COMPLETE,
            task_id=from_task.id,
            source_ref="test_seed",
            created_by=user.id,
        ),
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="plain-seed")

    # transferred=2: передача на следующий участок.
    result = await transfer_send(
        session,
        from_task_id=from_task.id,
        to_task_id=to_task.id,
        quantity=Decimal("2"),
        actor_id=user.id,
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="plain-transfer")

    row = await _ready_row(client, user, from_task.section_id, task_id=from_task.id)
    assert row["completed_quantity"] == "5"
    assert row["already_transferred_quantity"] == "2"
    # completed 5 − transferred 2 = 3; received 10 в бюджете не участвует.
    assert row["transferable_quantity"] == "3"

    transferable = await _task_transferable(session, from_task)
    assert transferable == Decimal("3")

    # Трёхсторонняя сверка (#119): write-guard ≡ read-SQL ≡ pure.
    from app.transfers.budget import remaining_plain

    sql_budgets = await _read_sql_budgets(session, from_task)
    assert sql_budgets["transferable"] == remaining_plain(Decimal("5"), Decimal("2"))
    assert sql_budgets["transferable"] == transferable
    # Бюджет отправки — отдельный столбец: release у нефинальной задачи
    # не вычитается из transferable (read-SQL больше не смешивает семантики).
    assert sql_budgets["sendable"] == Decimal("5")


# ─── 2. transform: строка выхода резки ───────────────────────────────────────


async def test_transform_ready_list_and_write_guard_agree_on_transferable(
    client, session
) -> None:
    """transform: produced=100, transferred=40 по выходу 900 → ready и guard = 60.

    Строка выхода (задача, размер): ``min(output 100, produced 100) −
    transferred 40`` (инвариант D2) — и ready-list, и write guard считают
    одно и то же. Второй выход (1800) не затронут → 100.
    """
    user = await _make_user(session, "tbc-saw@local")
    fx = await _make_transform_route_fixture(
        session,
        sku="TBCSAW",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    assert saw_task.outputs, "задание пилы должно нести выходы спецификации"
    await _complete_saw(session, saw_task=saw_task, user=user)

    result = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="transform-transfer")

    saw_sec = fx["sections"][1]
    row_900 = await _ready_row(
        client, user, saw_sec.id, task_id=saw_task.id, dims={"length_mm": 900}
    )
    assert row_900["completed_quantity"] == "100"
    assert row_900["already_transferred_quantity"] == "40"
    # min(output 100, produced 100) − transferred 40 = 60.
    assert row_900["transferable_quantity"] == "60"

    row_1800 = await _ready_row(
        client, user, saw_sec.id, task_id=saw_task.id, dims={"length_mm": 1800}
    )
    assert row_1800["transferable_quantity"] == "100"

    assert await _task_transferable(
        session, saw_task, dims={"length_mm": 900}
    ) == Decimal("60")
    assert await _task_transferable(
        session, saw_task, dims={"length_mm": 1800}
    ) == Decimal("100")


# ─── 3. stock: складская строка (section_plan_line_id) ───────────────────────


async def test_stock_ready_list_and_write_guard_agree_on_transferable(
    client, session
) -> None:
    """stock: план 100, физ. остаток 100, отгружено 40 → ready и guard = 60.

    Складская строка через ``compute_stock_section_transferable``
    (→ ``budget.remaining_stock``): после передачи и план-остаток, и
    физический остаток падают на 40 → ``min(60, 60) = 60``.
    """
    user = await _make_user(session, "tbc-stock@local")
    fx = await _make_dim_route_fixture(session, sku="TBCSTK", qty=Decimal("100"))
    raw_sec = fx["sections"][0]
    await _seed_balance(
        session,
        user_id=user.id,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
        qty=Decimal("100"),
        dimensions=None,
    )
    await _release_via_take_to_work(client, fx["position"].id)

    row_before = await _ready_row(client, user, raw_sec.id)
    # min(план 100, остаток 100) = 100.
    assert row_before["transferable_quantity"] == "100"
    fake_task_id = row_before["task_id"]

    # Отгрузка со склада 40 на первый производственный участок.
    result = await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="stock-transfer")

    row_after = await _ready_row(
        client, user, raw_sec.id, task_id=fake_task_id
    )
    assert row_after["already_transferred_quantity"] == "40"
    # min(план 100 − 40, физ. остаток 100 − 40) = 60.
    assert row_after["transferable_quantity"] == "60"

    fake_task = await session.get(WorkTask, fake_task_id)
    assert fake_task is not None
    assert await _task_transferable(session, fake_task) == Decimal("60")


# ─── 4. финальный участок: бюджет отправки (sendable) ────────────────────────


async def test_final_section_three_way_agrees_on_sendable(client, session) -> None:
    """Финальный участок (#119): pure ≡ read-SQL ≡ ready-строка на ``sendable``.

    produced=100 по выходу 900, выпущено (FINAL_RELEASE) 40 →
    ``remaining_send(100, 40) = 60``; готовая строка показывает те же 60
    («Отправить»), а бюджет передачи остаётся отдельным столбцом.
    """
    from app.services.shopfloor.operations_tasks import final_release
    from app.transfers.budget import remaining_send

    user = await _make_user(session, "tbc-final@local")
    fx = await _make_transform_route_fixture(
        session,
        sku="TBCFIN",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[{"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    result = await final_release(
        session,
        task_id=saw_task.id,
        quantity=Decimal("40"),
        actor_id=user.id,
    )
    await session.commit()
    assert result["transaction_id"]
    await assert_no_invariants_violations(session, context="final-send")

    # 1. pure: remaining_send клампит в ноль и считает остаток.
    produced = Decimal("100")
    released = Decimal("40")
    expected = remaining_send(produced, released)
    assert expected == Decimal("60")

    # 2. read-SQL: фабрика budget поверх ledger-подзапросов.
    budgets = await _read_sql_budgets(session, saw_task)
    assert budgets["sendable"] == expected
    assert budgets["sendable"] >= 0

    # 3. hydration ready-строки: смысл на финальном участке — отправка.
    saw_sec = fx["sections"][1]
    row_900 = await _ready_row(
        client, user, saw_sec.id, task_id=saw_task.id, dims={"length_mm": 900}
    )
    assert row_900["is_final"] is True
    assert row_900["transferable_quantity"] == "60"
