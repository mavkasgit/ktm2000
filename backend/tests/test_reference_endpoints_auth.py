"""Контракт входа на ЗАПИСЬ справочников.

Чтение справочников по решению владельца остаётся анонимно доступным и здесь
не сужается — единственное, что закрываем, это изменяющие ручки
(POST/PUT/PATCH/DELETE): аноним — 401, токен роли viewer — 403, токен роли
operator — проходит гвард. Гоняем настоящий вход: пользователь + активная
серверная сессия (claim sid).

Охваченные роутеры: products (в т.ч. пары), dimensions (типы и связи
продукта), sections, import-templates, spg, route-selection-rules,
route-rule-profiles.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services.session_service import issue_app_token

pytestmark = pytest.mark.asyncio


async def _headers_for(session: AsyncSession, role: UserRole, username: str) -> dict[str, str]:
    """Настоящий JWT роли: пользователь + активная серверная сессия (claim sid)."""
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"User {username}",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    token = await issue_app_token(session, user=user, login_method="oidc")
    await session.commit()
    return {"Authorization": f"Bearer {token}"}


# Ключи изменяющих ручек: по одной на каждый справочный роутер. Пути и тела
# строятся в момент прогона (см. _build_request), потому что ручки пар и
# размерностей адресуют продукт по id — без посева анонимный запрос падал бы
# на 404 «Product not found», и тест доказывал бы несуществующее.
_MUTATING_KEYS = [
    "products",
    "sections",
    "import_templates",
    "spg",
    "product_pairs",
    "dimension_types",
    "product_dimensions",
    "route_selection_rules",
    "route_rule_profiles",
]


def _build_request(key: str, seeded: dict[str, int]) -> tuple[str, str, Any]:
    """(метод, путь, тело) для изменяющей ручки — с посевом, где нужен."""
    match key:
        case "products":
            return "POST", "/api/products", {"sku": "AUTH-ANON", "name": "Anon product", "type": "component"}
        case "sections":
            return "POST", "/api/sections", {"code": "AUTH-ANON", "name": "Anon section", "spg_id": 1}
        case "import_templates":
            return "POST", "/api/import-templates", {"name": "Anon template"}
        case "spg":
            return "POST", "/api/spg", {"code": "AUTH-ANON", "name": "Anon spg"}
        case "product_pairs":
            return "POST", f"/api/products/{seeded['product_id']}/pairs", {"partner_product_id": seeded["partner_id"]}
        case "dimension_types":
            return "POST", "/api/dimension-types", {"code": "AUTH_ANON", "name": "Anon dim type", "unit": "mm"}
        case "product_dimensions":
            return (
                "POST",
                f"/api/products/{seeded['product_id']}/dimensions",
                {"dimension_type_id": seeded["dimension_type_id"]},
            )
        case "route_selection_rules":
            return (
                "POST",
                "/api/route-selection-rules",
                {"name": "Anon rule", "actions": [{"action": "set", "path": "ctx.marker"}]},
            )
        case "route_rule_profiles":
            return (
                "POST",
                "/api/route-rule-profiles",
                {"code": "AUTH-ANON", "name": "Anon profile", "route_sections": []},
            )
    raise AssertionError(f"unknown key {key}")


@pytest.fixture
async def seeded(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, int]]:
    """Два продукта и тип размерности, созданные ролью, которой запись полагается.

    Нужны, чтобы ручки пар и связей размерностей доходили до тела обработчика:
    гвард должен отбивать запрос, а не «продукт не найден».

    Строгий режим ставит общий `monkeypatch` фикстуры, а не свой: свой
    `MonkeyPatch` откатывался бы после отката фикстуры и оставлял
    `DEV_BYPASS_AUTH=False` на весь остаток воркера — следующий тест получил
    бы 401 вместо 200.
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _headers_for(session, UserRole.operator, "references_seeder")
    ids: dict[str, int] = {}
    for sku in ("AUTH-SEED-A", "AUTH-SEED-B"):
        res = await client.post(
            "/api/products",
            json={"sku": sku, "name": f"Seeded {sku}", "type": "component"},
            headers=headers,
        )
        assert res.status_code == 201, res.text
        ids["product_id" if sku.endswith("A") else "partner_id"] = res.json()["id"]
    dim = await client.post(
        "/api/dimension-types",
        json={"code": "AUTH_SEED", "name": "Seeded dim type", "unit": "mm"},
        headers=headers,
    )
    assert dim.status_code == 201, dim.text
    ids["dimension_type_id"] = dim.json()["id"]
    yield ids


@pytest.mark.parametrize("key", _MUTATING_KEYS)
async def test_anonymous_cannot_write_references(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, int],
    key: str,
) -> None:
    """Анонимный клиент не пишет ни в один из справочных роутеров."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    method, path, payload = _build_request(key, seeded)

    res = await client.request(method, path, json=payload)
    assert res.status_code == 401, res.text


@pytest.mark.parametrize("key", _MUTATING_KEYS)
async def test_viewer_cannot_write_references(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, int],
    key: str,
) -> None:
    """Viewer — режим «только чтение»: запись отбита на каждом справочнике."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _headers_for(session, UserRole.viewer, "references_viewer")
    method, path, payload = _build_request(key, seeded)

    res = await client.request(method, path, json=payload, headers=headers)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/products",
        "/api/sections",
        "/api/import-templates",
        "/api/spg",
        "/api/dimension-types",
        "/api/route-selection-rules",
        "/api/route-rule-profiles",
    ],
)
async def test_anonymous_still_reads_references(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """Чтение справочников по решению владельца остаётся анонимным."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)

    res = await client.get(path)
    assert res.status_code == 200, res.text


async def test_operator_may_create_product(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Роль, которой запись полагается (operator), проходит гвард."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _headers_for(session, UserRole.operator, "references_operator")

    created = await client.post(
        "/api/products",
        json={"sku": "AUTH-OPERATOR", "name": "Operator product", "type": "component"},
        headers=headers,
    )
    assert created.status_code not in (401, 403), created.text
