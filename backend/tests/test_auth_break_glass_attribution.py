"""Регрессии issue #180 / ADR-0027: атрибуция break-glass-записей.

Прод-инцидент: под break-glass (`DEV_BYPASS_AUTH=false`, своей строки в
`users` нет) эмулированный principal нёс `id = 0`, и первый же write-эндпоинт
падал 500 на `ForeignKeyViolationError: Key (created_by)=(0) is not present
in table "users"`.

Контракт (ADR-0027 п.1-4) проверяется снаружи, через публичные эндпоинты:
- импорт остатков под break-glass → 200, `created_by` = id служебной строки,
  `created_by_user_name` = «Emergency Access Admin»;
- ручная корректировка → 201 и валидный автор;
- `/auth/me` под break-glass по-прежнему `id = 0`, флаг аварийного доступа
  выставлен, правка профиля запрещена;
- служебной строки нет → явная ошибка 500 (сломанный деплой), а не FK.

Тесты не полагаются на `id = 1`: служебный id читается из сессии.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Product, ProductType, Section, User
from tests.test_integrity_invariants import assert_no_invariants_violations
from app.stock.models import StockTransaction

pytestmark = pytest.mark.asyncio

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Подпись аварийного режима в ledger (ADR-0027 п.4): отличает break-glass от
# автоматической записи служебного «System User».
_BREAK_GLASS_AUTHOR = "Emergency Access Admin"


# ─── Helpers ───────────────────────────────────────────────────────────────────


async def _system_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.username == "system"))
    assert user is not None, "conftest должен создать служебного пользователя"
    return user


async def _break_glass_headers(client: AsyncClient) -> dict[str, str]:
    """Получить настоящий break-glass-токен через публичный эндпоинт входа."""
    login = await client.post(
        "/api/auth/break-glass/login",
        json={"password": settings.BREAK_GLASS_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True
    )
    session.add(product)
    await session.flush()
    return product


async def _make_location(session: AsyncSession, code: str) -> Section:
    section = Section(code=code, name=code, type="raw_stock", is_active=True, sort_order=0)
    session.add(section)
    await session.flush()
    return section


def _remainders_xlsx(sku: str, quantity: float) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Остатки"
    ws.append(["SKU", "Количество", "Комментарий"])
    ws.append([sku, quantity, "под break-glass"])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─── Ledger-запись под break-glass ─────────────────────────────────────────────


async def test_import_remainders_under_break_glass_attributes_to_system_user(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Импорт остатков под break-glass → 200 и автор — служебный пользователь."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system_user = await _system_user(session)
    product = await _make_product(session, "BG-IMPORT-001")
    location = await _make_location(session, "BG-IMPORT-LOC")
    await session.commit()
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/stock/import/remainders",
        files={"file": ("remainders.xlsx", _remainders_xlsx("BG-IMPORT-001", 100), _XLSX_MIME)},
        data={"location_id": str(location.id), "sheet_index": "0", "skip_invalid": "true"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 1
    assert len(body["transaction_ids"]) == 1

    tx = await session.get(StockTransaction, body["transaction_ids"][0])
    assert tx is not None
    assert tx.product_id == product.id
    assert tx.to_location_id == location.id
    # Валидный автор: id служебной строки, а не 0 (эмулированный principal).
    assert tx.created_by == system_user.id
    assert tx.created_by_user_name == _BREAK_GLASS_AUTHOR
    await assert_no_invariants_violations(session, context="break-glass import")


async def test_manual_adjustment_under_break_glass_attributes_to_system_user(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ручная корректировка под break-glass → 201 и автор — служебный пользователь."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system_user = await _system_user(session)
    product = await _make_product(session, "BG-ADJ-001")
    location = await _make_location(session, "BG-ADJ-LOC")
    await session.commit()
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/stock/adjustment",
        json={
            "product_id": product.id,
            "location_id": location.id,
            "quantity": 25.0,
            "reason": "manual_in",
            "comment": "под break-glass",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text

    tx = await session.get(StockTransaction, response.json()["id"])
    assert tx is not None
    assert tx.created_by == system_user.id
    assert tx.created_by_user_name == _BREAK_GLASS_AUTHOR
    await assert_no_invariants_violations(session, context="break-glass adjustment")


async def test_break_glass_without_system_row_fails_explicitly_not_fk(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нет служебной строки → явная ошибка деплоя (500 JSON), не FK-нарушение.

    Отсутствие служебного пользователя означает сломанный деплой (ADR-0027 п.2),
    а не штатный режим: молчаливого отката к `id = 0` и падения в FK быть не должно.
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    await session.execute(delete(User).where(User.username == "system"))
    await session.commit()
    assert await session.scalar(select(User).where(User.username == "system")) is None

    product = await _make_product(session, "BG-NOSYS-001")
    location = await _make_location(session, "BG-NOSYS-LOC")
    await session.commit()
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/stock/import/remainders",
        files={"file": ("remainders.xlsx", _remainders_xlsx("BG-NOSYS-001", 10), _XLSX_MIME)},
        data={"location_id": str(location.id), "sheet_index": "0"},
        headers=headers,
    )

    # Явная ошибка, а не необработанный IntegrityError (который httpx пробросил бы
    # наружу, а не вернул как ответ).
    assert response.status_code == 500, response.text
    assert response.headers.get("content-type", "").startswith("application/json")
    detail = response.json()["detail"]
    assert detail
    lowered = detail.lower()
    # Сообщение называет отсутствующую служебную строку…
    assert "system" in lowered or "служебн" in lowered
    # …и это не всплывшее нарушение внешнего ключа.
    assert "foreign key" not in lowered
    assert "created_by" not in lowered

    # Никаких следов тихой записи с невалидным автором.
    assert (await session.execute(select(StockTransaction))).scalars().all() == []


# ─── Контракт /auth/me под break-glass ─────────────────────────────────────────


async def test_break_glass_me_has_id_zero_and_profile_patch_forbidden(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/auth/me` под break-glass: id = 0, флаг выставлен, правка профиля — 403.

    Атрибуционный id служебной строки — внутренний: наружу «своей записи нет»
    по-прежнему выражается `id = 0` (ADR-0027 п.6).
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _break_glass_headers(client)

    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == 0
    assert body["is_break_glass"] is True
    assert body["full_name"] == _BREAK_GLASS_AUTHOR

    patch = await client.patch(
        "/api/auth/me/profile",
        json={"theme": "dark"},
        headers=headers,
    )
    assert patch.status_code == 403, patch.text
