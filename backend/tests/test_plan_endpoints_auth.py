"""Контракт входа на план-импортные ручки (`/api/production-plans`, `/api/imports`).

Раньше читающие ручки этих модулей были открыты анониму — включая скачивание
исходного xlsx, — а пишущие требовали лишь валидный токен: `viewer` и
`transporter` утверждали позиции, правили количество и сносили батч импорта с
каскадом. Плюс одиночные мутации были открыты всем, а их массовые близнецы
держали `WRITER_ROLES` (admin, section_manager, operator), то есть `planner` —
владелец раздела `/planning` — получал 403 на массовой кнопке (issue #235).

Матрица: `PLAN_OWNER_ROLES` / `PLAN_WRITER_ROLES` в `app/api/deps.py`, ADR-0057.
Тест держит две вещи: наблюдаемый статус на живых ручках и полноту матрицы —
обход маршрутов приложения сверяется с таблицей ниже, поэтому новый
план-импортный маршрут без гейта (или с чужим набором) валит прогон.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PLAN_OWNER_ROLES, PLAN_WRITER_ROLES, READER_ROLES
from app.core.config import settings
from app.main import app
from app.models.production_plan import PlanPositionStatus
from app.models.user import UserRole
from tests.helpers.auth import user_headers
from tests.helpers.plan import make_plan_with_positions

# Асинхронные тесты помечает pytest-asyncio сам (`asyncio_mode = auto` в
# backend/pytest.ini). Модульный `pytestmark = pytest.mark.asyncio` вешал маркер
# и на синхронный `test_plan_import_route_matrix_is_complete` — pytest
# предупреждал об этом на каждом прогоне; здесь маркер был лишним.

ADMIN_ONLY = frozenset({UserRole.admin})

#: Минимально допустимая роль на каждый план-импортный путь. Ключ — (метод, путь).
EXPECTED_GUARDS: dict[tuple[str, str], frozenset[UserRole]] = {
    ("GET", "/api/production-plans"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/preview"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/positions/{position_id}/history"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/positions/{position_id}/route-check"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/section-totals"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/files"): READER_ROLES,
    ("GET", "/api/production-plans/all-files"): READER_ROLES,
    ("GET", "/api/production-plans/all-positions"): READER_ROLES,
    ("GET", "/api/production-plans/cancelled-positions"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/all-positions"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/duplicates"): READER_ROLES,
    ("GET", "/api/production-plans/{production_plan_id}/batches/{batch_id}/preview"): READER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/{position_id}/approve"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/{position_id}/cancel"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/{position_id}/restore"): PLAN_WRITER_ROLES,
    ("DELETE", "/api/production-plans/{production_plan_id}/positions/{position_id}"): PLAN_WRITER_ROLES,
    ("PATCH", "/api/production-plans/{production_plan_id}/positions/{position_id}/quantity"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/release-batches"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/positions/batch-assign-route"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/batch-assign-route"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/bulk-approve"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/positions/bulk-delete"): PLAN_WRITER_ROLES,
    ("POST", "/api/production-plans/{production_plan_id}/change-sets/{change_set_id}/apply"): ADMIN_ONLY,
    ("POST", "/api/production-plans/{production_plan_id}/change-sets/{change_set_id}/rollback"): ADMIN_ONLY,
    ("DELETE", "/api/production-plans/{production_plan_id}/change-sets/{change_set_id}"): ADMIN_ONLY,
    ("DELETE", "/api/production-plans/{production_plan_id}/batches/{batch_id}"): ADMIN_ONLY,
    ("POST", "/api/production-plans/{production_plan_id}/batches/{batch_id}/hide"): ADMIN_ONLY,
    ("GET", "/api/production-plans/{production_plan_id}/delete-preview"): ADMIN_ONLY,
    ("DELETE", "/api/production-plans/{production_plan_id}"): ADMIN_ONLY,
    ("GET", "/api/production-plans/{production_plan_id}/batches/{batch_id}/force-delete-preview"): ADMIN_ONLY,
    ("DELETE", "/api/production-plans/{production_plan_id}/batches/{batch_id}/force"): ADMIN_ONLY,
    ("POST", "/api/production-plans/reset-all"): ADMIN_ONLY,
    ("POST", "/api/imports/excel"): PLAN_OWNER_ROLES,
    ("POST", "/api/imports/excel/simulate"): PLAN_OWNER_ROLES,
    ("POST", "/api/imports/excel/sheets"): READER_ROLES,
    ("POST", "/api/imports/excel/preview"): READER_ROLES,
    ("GET", "/api/imports/batches/{batch_id}/items"): READER_ROLES,
    ("GET", "/api/imports/items/{item_id}"): READER_ROLES,
    ("GET", "/api/imports/recent"): READER_ROLES,
    ("GET", "/api/imports/{batch_id}/positions"): READER_ROLES,
    ("GET", "/api/imports/files/{file_id}/download"): READER_ROLES,
}

@pytest.fixture(autouse=True)
def _strict_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Модуль проверяет роли — только strict-режим.

    В dev-ветке запрос без токена достаётся `system@local` (admin), и 401 не
    отличить от «гейт пропустил».
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)


def _iter_api_routes(routes, prefix: str) -> list[tuple[str, APIRoute]]:
    """Плоский список (полный путь, маршрут): включённые роутеры лежат вложенно.

    FastAPI 0.142 отдаёт результат `include_router` обёрткой `_IncludedRouter`
    с полем `original_router` — публичного обхода с готовыми путями нет. При
    обновлении FastAPI это место проверяется первым: тест упадёт на
    расхождении таблицы со списком, а не промолчит.
    """
    out: list[tuple[str, APIRoute]] = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            out.extend(_iter_api_routes(included.routes, prefix + (getattr(route, "prefix", "") or "")))
        elif isinstance(route, APIRoute):
            out.append((prefix + route.path, route))
        elif hasattr(route, "routes"):
            out.extend(_iter_api_routes(route.routes, prefix + (getattr(route, "prefix", "") or "")))
    return out


def _declared_roles(dependant) -> frozenset[UserRole] | None:
    """Пересечение наборов всех ролевых зависимостей маршрута (или None)."""
    found: list[frozenset[UserRole]] = []
    stack = [dependant]
    seen: set[int] = set()
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        allowed = getattr(call, "allowed_roles", None)
        if allowed is not None and id(call) not in seen:
            seen.add(id(call))
            found.append(frozenset(allowed))
        stack.extend(getattr(dep, "dependencies", []))
    if not found:
        return None
    result = found[0]
    for roles in found[1:]:
        result &= roles
    return result


def _collect_guards() -> dict[tuple[str, str], frozenset[UserRole] | None]:
    guards: dict[tuple[str, str], frozenset[UserRole] | None] = {}
    for path, route in _iter_api_routes(app.routes, "/api"):
        if not (path.startswith("/api/production-plans") or path.startswith("/api/imports")):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            guards[(method, path)] = _declared_roles(route.dependant)
    return guards


def _assert_gate_passed(response) -> None:
    """Ручка дошла до бизнес-слоя: не 401/403 (гейт) и не 5xx (поломка).

    Какой именно бизнес-статус вернулся, решает не этот тест: тела запросов
    здесь заведомо неполные, и предмет проверки — вход, а не данные.
    """
    assert response.status_code not in (401, 403), response.text
    assert response.status_code < 500, response.text


def test_plan_import_route_matrix_is_complete() -> None:
    """Каждый план-импортный путь объявляет минимально допустимую роль.

    Таблица `EXPECTED_GUARDS` — не справка, а контракт: расхождение в любую
    сторону валит тест — пропавший путь, новый путь без записи, снятый гейт,
    чужой набор ролей.
    """
    actual = _collect_guards()

    missing = set(EXPECTED_GUARDS) - set(actual)
    assert not missing, f"план-импортный маршрут пропал или переименован: {sorted(missing)}"
    unlisted = set(actual) - set(EXPECTED_GUARDS)
    assert not unlisted, f"новый план-импортный путь без записи в таблице гейтов: {sorted(unlisted)}"

    for key, expected in EXPECTED_GUARDS.items():
        assert actual[key] == expected, f"{key[0]} {key[1]}: ожидался {expected}, объявлен {actual[key]}"


async def test_anonymous_cannot_reach_plan_and_import_endpoints(
    client: AsyncClient,
) -> None:
    """Без токена — 401 и на чтении, и на мутации, включая скачивание xlsx."""
    assert (await client.get("/api/production-plans")).status_code == 401
    assert (await client.get("/api/imports/recent")).status_code == 401
    assert (await client.get("/api/imports/files/1/download")).status_code == 401
    assert (await client.post("/api/production-plans/1/positions/1/approve")).status_code == 401
    assert (await client.post("/api/production-plans/1/positions/bulk-approve", json={"ids": [1]})).status_code == 401


async def test_all_reader_roles_still_read_plans_and_imports(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чтение открыто всем шести ролям: каждая видит и планы, и историю импорта."""
    for role in READER_ROLES:
        _, headers = await user_headers(session, role, f"plan_reader_{role.value}")

        assert (await client.get("/api/production-plans", headers=headers)).status_code == 200, role
        assert (await client.get("/api/imports/recent", headers=headers)).status_code == 200, role


async def test_viewer_transporter_and_operator_cannot_mutate_plan(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Мутации плана — не для зрителя, транспортировщика и оператора.

    Оператор исключён набором `PLAN_WRITER_ROLES` (issue #235): разделов
    `/planning` и `/execution`, где нарисованы эти кнопки, у него нет.
    """
    mutations = [
        ("post", "/api/production-plans/1/positions/1/approve", None),
        ("post", "/api/production-plans/1/positions/1/cancel", None),
        ("post", "/api/production-plans/1/positions/1/restore", None),
        ("delete", "/api/production-plans/1/positions/1", None),
        ("patch", "/api/production-plans/1/positions/1/quantity", {"quantity": "5"}),
        ("post", "/api/production-plans/1/release-batches", {}),
        ("post", "/api/production-plans/1/positions/batch-assign-route", {"position_ids": [1], "route_id": 1}),
        ("post", "/api/production-plans/positions/batch-assign-route", {"position_ids": [1], "route_id": 1}),
        ("post", "/api/production-plans/1/positions/bulk-approve", {"ids": [1]}),
        ("post", "/api/production-plans/1/positions/bulk-delete", {"ids": [1]}),
        ("post", "/api/production-plans/1/change-sets/1/apply", None),
        ("delete", "/api/production-plans/1/batches/1", None),
    ]
    for role, username in (
        (UserRole.viewer, "plan_viewer"),
        (UserRole.transporter, "plan_transporter"),
        (UserRole.operator, "plan_operator"),
    ):
        _, headers = await user_headers(session, role, username)
        for method, url, body in mutations:
            response = await getattr(client, method)(
                url, headers=headers, **({"json": body} if body is not None else {})
            )
            assert response.status_code == 403, f"{role.value}: {method.upper()} {url} → {response.status_code}"


async def test_planner_can_bulk_approve_positions(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Владелец плана утверждает пачкой: planner получает 200, а не 403.

    Одиночная и массовая кнопки утверждения обязаны пускать одну и ту же роль —
    иначе кнопка на экране планировщика обманка (issue #235).
    """
    _, headers = await user_headers(session, UserRole.planner, "plan_planner")
    plan, positions, _ = await make_plan_with_positions(session, "FG-AUTH-BULK", 2)

    response = await client.post(
        f"/api/production-plans/{plan.id}/positions/bulk-approve",
        json={"ids": [p.id for p in positions]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert {r["status"] for r in response.json()["results"]} == {"success"}
    assert all(p.status == PlanPositionStatus.approved for p in positions)


async def test_planner_creates_import_but_does_not_commit_it(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Мастер импорта — planning-ручка, коммит батча — admin.

    Создание батча (`/imports/excel`, `/excel/simulate`) идёт набором владельца
    плана, а `apply`/`rollback`/`discard`/удаление батча — сильнее создания и
    потому админские (ADR-0057).
    """
    _, planner = await user_headers(session, UserRole.planner, "plan_importer")
    _, admin = await user_headers(session, UserRole.admin, "plan_importer_admin")

    _assert_gate_passed(await client.post(
        "/api/imports/excel/simulate",
        json={"rows": [], "template_id": 999999},
        headers=planner,
    ))
    _assert_gate_passed(await client.post(
        "/api/imports/excel",
        data={"template_id": "999999"},
        headers=planner,
    ))

    assert (
        await client.post("/api/production-plans/1/change-sets/1/apply", headers=planner)
    ).status_code == 403
    _assert_gate_passed(await client.post("/api/production-plans/1/change-sets/1/apply", headers=admin))
