"""Обход маршрутов приложения и чтение объявленных на них ролей.

Нужен тестам-матрицам («у каждого пути X есть гейт N»): они сверяют не только
наблюдаемый статус на живых ручках, но и полноту таблицы — новый путь без
записи или без гейта валит прогон.

FastAPI 0.142 отдаёт результат `include_router` обёрткой `_IncludedRouter` с
полем `original_router` — публичного обхода с готовыми путями нет. При
обновлении FastAPI это место проверяется первым: тест упадёт на расхождении
таблицы со списком, а не промолчит.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.models.user import UserRole
from fastapi.routing import APIRoute


def iter_api_routes(
    routes: Iterable,
    prefix: str = "",
) -> list[tuple[str, APIRoute]]:
    """Плоский список (полный путь, маршрут): включённые роутеры лежат вложенно."""
    out: list[tuple[str, APIRoute]] = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            out.extend(
                iter_api_routes(included.routes, prefix + (getattr(route, "prefix", "") or ""))
            )
        elif isinstance(route, APIRoute):
            out.append((prefix + route.path, route))
        elif hasattr(route, "routes"):
            out.extend(
                iter_api_routes(route.routes, prefix + (getattr(route, "prefix", "") or ""))
            )
    return out


def declared_roles(dependant) -> frozenset[UserRole] | None:
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


def collect_guards(
    app,
    *,
    prefix: str = "/api",
    path_prefixes: tuple[str, ...] = (),
) -> dict[tuple[str, str], frozenset[UserRole] | None]:
    """Таблица {(метод, полный путь): объявленные роли} по маршрутам приложения."""
    guards: dict[tuple[str, str], frozenset[UserRole] | None] = {}
    for path, route in iter_api_routes(app.routes, prefix):
        if path_prefixes and not path.startswith(path_prefixes):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            guards[(method, path)] = declared_roles(route.dependant)
    return guards
