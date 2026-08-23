"""REST-тесты list-endpoint GET /actions (тикет #117).

Пагинация page/page_size, фильтры action_type/status, сортировка по id desc.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.action_journal_service import action_journal_service

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await action_journal_service.log(
        session, action_type="transfer_send", ref_id=101, actor="Иван"
    )
    await action_journal_service.log(
        session, action_type="task_complete", ref_id=202, actor="Мария"
    )
    await action_journal_service.log(
        session, action_type="transfer_send", ref_id=303, actor="Иван"
    )
    await session.commit()


async def test_list_returns_items_with_pagination(
    session: AsyncSession, auth_client
) -> None:
    await _seed(session)
    resp = await auth_client.get("/api/actions")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 3
    assert data["page"] == 1
    assert data["page_size"] == 50
    ids = [item["id"] for item in data["items"]]
    assert ids == sorted(ids, reverse=True)  # сортировка id desc
    first = data["items"][0]
    assert {
        "id",
        "action_type",
        "ref_id",
        "actor",
        "status",
        "depends_on",
        "created_at",
    } <= set(first)


async def test_list_filters_by_type_and_status(
    session: AsyncSession, auth_client
) -> None:
    await _seed(session)
    resp = await auth_client.get("/api/actions", params={"action_type": "transfer_send"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items
    assert all(item["action_type"] == "transfer_send" for item in items)

    resp = await auth_client.get("/api/actions", params={"status": "active"})
    assert resp.status_code == 200, resp.text
    assert all(item["status"] == "active" for item in resp.json()["items"])

    bad = await auth_client.get("/api/actions", params={"status": "bogus"})
    assert bad.status_code == 422


async def test_list_pagination_slices(session: AsyncSession, auth_client) -> None:
    await _seed(session)
    page1 = await auth_client.get("/api/actions", params={"page": 1, "page_size": 2})
    page2 = await auth_client.get("/api/actions", params={"page": 2, "page_size": 2})
    assert page1.status_code == 200 and page2.status_code == 200
    ids1 = [i["id"] for i in page1.json()["items"]]
    ids2 = [i["id"] for i in page2.json()["items"]]
    assert len(ids1) == 2
    # page вне допустимых значений → 422
    bad = await auth_client.get("/api/actions", params={"page": 0})
    assert bad.status_code == 422
