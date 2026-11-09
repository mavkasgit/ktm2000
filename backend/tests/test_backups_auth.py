"""Сторож [#409]: у `/api/backups` должна быть настоящая авторизация.

Сейчас `_validate_admin` — заглушка (`current_user: str = "admin"`), поэтому
любой анонимный запрос проходит. Тест написан как ``xfail(strict=True)``: пока
дыра есть, он «падает» ожидаемо и не красит прогон; когда авторизацию починят,
он станет зелёным и **сломает прогон** — это напоминание снять маркер и
закрыть #409, а не забыть про блокер деплоя.

Тикет: https://github.com/mavkasgit/ktm2000/issues/409
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.xfail(
    strict=True,
    reason="[#409] /api/backups: _validate_admin — заглушка; снять xfail после фикса",
)
async def test_anonymous_cannot_list_backups(client: AsyncClient) -> None:
    response = await client.get("/api/backups")

    assert response.status_code in (401, 403), response.text
