"""API-покрытие стратегий недостачи (#133, до-покрытие ревью).

Сценарий «введено 100 / на складе 80» через POST
``/api/shopfloor/tasks/{id}/complete`` для каждой из трёх стратегий,
дефолт без ``shortage_strategy`` (одиночный complete и bulk-complete
entry), а также negative_remainder с браком: на обычной секции обе
проводки уходят в минус, на requires_lot СПГ операция отклоняется
атомарно.

Топология переиспользуется из тестового модуля трансформации
(``tests.stock.test_task_completion_transform``).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.defect import Defect
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import QualityState, Reason

from tests.stock.helpers import canon_scrap_section_id
from tests.stock.test_task_completion_transform import (
    DIMS_IN,
    _balance,
    _make_transform_setup,
    _receive_input,
    _tx_sum,
)

pytestmark = pytest.mark.asyncio


def _auth_headers(fx: dict) -> dict[str, str]:
    """JWT оператора из фикстуры трансформации (subject = email)."""
    return {"Authorization": f"Bearer {create_access_token(subject=fx['user'].email)}"}


# ─── три стратегии: введено 100 / на складе 80 ───────────────────────────────


async def test_api_shortage_fail_returns_400_naming_available(
    client, session: AsyncSession,
) -> None:
    """fail → HTTP 400, detail называет доступное количество; ledger чист."""
    fx = await _make_transform_setup(session, sku="API-SFAIL")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "shortage_strategy": "fail"},
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 400, resp.text
    assert "доступно 80" in resp.json()["detail"]

    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_IN) == Decimal("80")


async def test_api_shortage_partial_clamps_and_reports_completed_quantity(
    client, session: AsyncSession,
) -> None:
    """partial → 200, проведено 80, ответ содержит completed_quantity=80,
    задача частично выполнена."""
    fx = await _make_transform_setup(session, sku="API-SPART")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0", "shortage_strategy": "partial"},
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(str(data["completed_quantity"])) == Decimal("80")
    assert data["status"] == WorkTaskStatus.partially_completed.value

    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("80")
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_IN) == Decimal("0")

    task = await session.get(WorkTask, fx["task"].id)
    assert task is not None
    assert task.status == WorkTaskStatus.partially_completed


async def test_api_negative_remainder_drives_input_balance_minus(
    client, session: AsyncSession,
) -> None:
    """negative_remainder → 200, полный порция; баланс входа на участке −20."""
    fx = await _make_transform_setup(session, sku="API-SNEG")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={
            "good_quantity": "100",
            "defect_quantity": "0",
            "shortage_strategy": "negative_remainder",
        },
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 200, resp.text

    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("100")
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_IN) == Decimal("-20")


# ─── дефолт: без явной стратегии = fail ──────────────────────────────────────


async def test_api_single_complete_without_strategy_is_fail(
    client, session: AsyncSession,
) -> None:
    """POST без shortage_strategy ведёт себя как fail (#133)."""
    fx = await _make_transform_setup(session, sku="API-SDEF")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={"good_quantity": "100", "defect_quantity": "0"},
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 400, resp.text
    assert "доступно 80" in resp.json()["detail"]
    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")


async def test_api_bulk_entry_without_strategy_is_fail(
    client, session: AsyncSession,
) -> None:
    """Bulk-complete entry без shortage_strategy: элемент failed с той же
    ошибкой, ledger без записей."""
    fx = await _make_transform_setup(session, sku="API-BDEF")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        "/api/shopfloor/tasks/bulk-complete",
        json={"entries": [
            {"task_id": fx["task"].id, "good_quantity": "100", "defect_quantity": "0"},
        ]},
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 200, resp.text  # конверт bulk всегда 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert "доступно 80" in (results[0]["reason"] or "")

    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_IN) == Decimal("80")


# ─── negative_remainder + брак ────────────────────────────────────────────────


async def test_api_negative_with_defect_both_postings_go_minus(
    client, session: AsyncSession,
) -> None:
    """Обычная секция: good 90 + defect 10 при остатке 80 — и списание входа,
    и SCRAP проводятся, GOOD-баланс входной группы уходит в −20."""
    fx = await _make_transform_setup(session, sku="API-SNDEF")
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={
            "good_quantity": "90",
            "defect_quantity": "10",
            "shortage_strategy": "negative_remainder",
        },
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(str(data["completed_quantity"])) == Decimal("100")

    product_id, saw_id = fx["product"].id, fx["saw"].id
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("90")
    assert await _tx_sum(session, fx["task"].id, Reason.SCRAP, DIMS_IN) == Decimal("10")
    # Обе проводки легли на одну GOOD-группу входа: 80 − 90 − 10 = −20.
    assert await _balance(session, product_id, saw_id, DIMS_IN) == Decimal("-20")
    # Брак дошёл до канонической SCRAP-секции (код политики, #134).
    canon_scrap_id = await canon_scrap_section_id(session)
    assert await _balance(
        session, product_id, canon_scrap_id, DIMS_IN, QualityState.SCRAP,
    ) == Decimal("10")


async def test_api_requires_lot_blocks_negative_with_defect_atomically(
    client, session: AsyncSession,
) -> None:
    """requires_lot СПГ: negative_remainder с браком отклоняет всю операцию —
    ни минуса, ни SCRAP-проводки, ни Defect."""
    fx = await _make_transform_setup(session, sku="API-SLOT2", spg_requires_lot=True)
    await _receive_input(session, fx, quantity=Decimal("80"))

    resp = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={
            "good_quantity": "90",
            "defect_quantity": "10",
            "shortage_strategy": "negative_remainder",
        },
        headers=_auth_headers(fx),
    )
    assert resp.status_code == 400, resp.text
    assert "requires_lot" in resp.json()["detail"]

    # Атомарность: баланс не тронут, проводок нет, брак не создан.
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_IN) == Decimal("80")
    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")
    assert await _tx_sum(
        session, fx["task"].id, Reason.SCRAP, any_dims=True,
    ) == Decimal("0")
    defects = (
        await session.scalars(select(Defect).where(Defect.task_id == fx["task"].id))
    ).all()
    assert defects == []
