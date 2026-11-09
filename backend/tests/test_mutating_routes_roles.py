"""Изменяющие ручки не открыты роли «только чтение».

Регресс: ``POST/PATCH/DELETE /shopfloor/sections/{id}/operations`` держали
``READER_ROLES`` (включая viewer и transporter), тогда как фронт прячет
кнопки правки у ролей без ``editReferences``. Системная проверка ловит
любую новую такую ручку; read-only POST (предпросмотры/разбор файла)
перечислены явно и обязаны остаться в списке.
"""
from __future__ import annotations

from app.api.deps import READER_ROLES
from app.main import app

from tests.test_plan_endpoints_auth import _declared_roles, _iter_api_routes

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# POST, который ничего не меняет: предпросмотры и разбор загруженного файла.
READ_ONLY_POSTS = {
    ("POST", "/api/imports/excel/sheets"),
    ("POST", "/api/imports/excel/preview"),
    ("POST", "/api/production-planning/rows/{position_id}/issue-preview"),
}


def _mutating_guards() -> dict[tuple[str, str], frozenset]:
    guards: dict[tuple[str, str], frozenset] = {}
    for path, route in _iter_api_routes(app.routes, "/api"):
        methods = route.methods & MUTATING_METHODS
        if not methods:
            continue
        roles = _declared_roles(route.dependant)
        if roles is None:
            continue
        for method in sorted(methods):
            guards[(method, path)] = roles
    return guards


def test_mutating_routes_are_not_open_to_viewer() -> None:
    guards = _mutating_guards()

    stale_allowlist = READ_ONLY_POSTS - set(guards)
    assert not stale_allowlist, (
        f"read-only POST исчез или переименован: {sorted(stale_allowlist)}"
    )

    offenders = sorted(
        key
        for key, roles in guards.items()
        if key not in READ_ONLY_POSTS and "viewer" in {role.value for role in roles}
    )
    assert not offenders, (
        "изменяющая ручка открыта роли viewer: "
        f"{offenders}. Если это read-only POST — добавьте его в READ_ONLY_POSTS."
    )


def test_read_only_post_allowlist_keeps_reader_roles() -> None:
    """Исключение не должно тихо сузить набор: это по-прежнему чтение."""
    guards = _mutating_guards()
    for key in READ_ONLY_POSTS:
        assert guards[key] == frozenset(READER_ROLES), key


# Точечное исключение из общего правила: эти ручки закрыты не только для
# viewer, но и для transporter. Передачи и «взять в работу» transporter
# открыты намеренно, поэтому общий тест выше проверяет только viewer.
SECTION_OPERATION_ROUTES = {
    ("POST", "/api/shopfloor/sections/{section_id}/operations"),
    ("PATCH", "/api/shopfloor/sections/{section_id}/operations/{op_id}"),
    ("DELETE", "/api/shopfloor/sections/{section_id}/operations/{op_id}"),
}


def test_section_operations_are_not_open_to_transporter() -> None:
    guards = _mutating_guards()

    for key in SECTION_OPERATION_ROUTES:
        assert key in guards, f"ручка исчезла или переименована: {key}"
        assert "transporter" not in {role.value for role in guards[key]}, key
