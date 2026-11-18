"""Контракт входа `/api/backups`: admin-only (issue #409).

Раньше здесь стояла заглушка `_validate_admin(current_user: str = "admin")`:
проверка проходила всегда, а «пользователь» приходил query-параметром, который
клиент подменял. Любой, кто дотягивался до API, мог создать/удалить бэкап,
восстановить БД и скачать файл из каталога бэкапов.

Политика: все ручки `/api/backups` — `UserRole.admin` через `require_role`.
Тест держит две вещи сразу: наблюдаемый статус на живых ручках (аноним — 401,
viewer/transporter — 403, admin проходит) и полноту матрицы — обход маршрутов
приложения сверяется с таблицей ниже, поэтому новая ручка бэкапов без гейта
валит прогон.

Тикет: https://github.com/mavkasgit/ktm2000/issues/409
"""
from __future__ import annotations

from pathlib import Path

import pytest
from app.api import backups as backups_api
from app.core.config import settings
from app.main import app
from app.models.user import UserRole
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.auth import user_headers
from tests.helpers.routes import collect_guards

ADMIN_ONLY = frozenset({UserRole.admin})

#: Минимально допустимая роль на каждый путь `/api/backups`. Ключ — (метод, путь).
#: Таблица — контракт: расхождение в любую сторону (пропавший путь, новый путь
#: без записи, снятый или ослабленный гейт) валит прогон.
EXPECTED_GUARDS: dict[tuple[str, str], frozenset[UserRole]] = {
    ("GET", "/api/backups"): ADMIN_ONLY,
    ("POST", "/api/backups"): ADMIN_ONLY,
    ("POST", "/api/backups/jobs"): ADMIN_ONLY,
    ("GET", "/api/backups/jobs/{job_id}"): ADMIN_ONLY,
    ("GET", "/api/backups/config"): ADMIN_ONLY,
    ("PATCH", "/api/backups/config"): ADMIN_ONLY,
    ("GET", "/api/backups/current-preview"): ADMIN_ONLY,
    ("GET", "/api/backups/{filename}/download"): ADMIN_ONLY,
    ("PATCH", "/api/backups/{filename}/comment"): ADMIN_ONLY,
    ("DELETE", "/api/backups/{filename}"): ADMIN_ONLY,
    ("POST", "/api/backups/{filename}/preview"): ADMIN_ONLY,
    ("POST", "/api/backups/{filename}/restore"): ADMIN_ONLY,
    ("POST", "/api/backups/bulk-delete"): ADMIN_ONLY,
    ("POST", "/api/backups/delete-older-than"): ADMIN_ONLY,
    ("POST", "/api/backups/upload-preview"): ADMIN_ONLY,
    ("POST", "/api/backups/upload-restore"): ADMIN_ONLY,
}

_UPLOAD = {"files": {"file": ("probe.zip", b"PK\x03\x04", "application/zip")}}

#: Запросы, по одному на каждую ручку. Тела безопасные: гейт роли срабатывает
#: до чтения файлов и БД, поэтому целиться в существующие бэкапы не нужно, а
#: multipart отправляется настоящий — иначе отказ пришёл бы от валидации тела
#: (422), а не от гейта, и тест доказывал бы не то.
_PROBES: list[tuple[str, str, dict]] = [
    ("GET", "/api/backups", {}),
    ("GET", "/api/backups/config", {}),
    ("GET", "/api/backups/current-preview", {}),
    ("GET", "/api/backups/jobs/abc", {}),
    ("GET", "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip/download", {}),
    ("PATCH", "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip/comment", {"json": {"comment": "x"}}),
    ("DELETE", "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip", {}),
    ("POST", "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip/preview", {}),
    ("POST", "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip/restore", {"json": {"db_name": "x"}}),
    ("POST", "/api/backups/bulk-delete", {"json": {"filenames": ["x.zip"]}}),
    ("POST", "/api/backups/delete-older-than", {"json": {"days": 1}}),
    ("POST", "/api/backups", {}),
    ("POST", "/api/backups/jobs", {}),
    ("PATCH", "/api/backups/config", {"json": {"auto_enabled": False, "time_of_day": "23:00"}}),
    ("POST", "/api/backups/upload-preview", _UPLOAD),
    ("POST", "/api/backups/upload-restore", _UPLOAD),
]


@pytest.fixture(autouse=True)
def _strict_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Модуль проверяет роли — только strict-режим.

    В dev-ветке (`DEV_BYPASS_AUTH`) запрос без токена достаётся `system@local`
    (admin), и 401 не отличить от «гейт пропустил». Отдельного флага для
    бэкапов нет и не нужно: стенд остаётся рабочим через тот же
    `DEV_BYPASS_AUTH`, что и остальной API.
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)


@pytest.fixture
def backups_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пустой каталог бэкапов: ручки не читают и не пишут в `data/backups`."""
    directory = tmp_path / "backups"
    directory.mkdir()
    monkeypatch.setattr(backups_api, "BACKUPS_DIR", directory)
    return directory


def test_backups_route_matrix_is_admin_only() -> None:
    """Каждый путь `/api/backups` объявляет ровно admin — и таблица полна."""
    actual = collect_guards(app, path_prefixes=("/api/backups",))

    missing = set(EXPECTED_GUARDS) - set(actual)
    assert not missing, f"ручка бэкапов пропала или переименована: {sorted(missing)}"
    unlisted = set(actual) - set(EXPECTED_GUARDS)
    assert not unlisted, f"новая ручка бэкапов без записи в таблице гейтов: {sorted(unlisted)}"

    for key, expected in EXPECTED_GUARDS.items():
        assert actual[key] == expected, f"{key[0]} {key[1]}: ожидался {expected}, объявлен {actual[key]}"


async def test_anonymous_cannot_reach_backups(
    client: AsyncClient,
    backups_dir: Path,
) -> None:
    """Без токена — 401 на каждой ручке: список, конфиг, скачивание, restore."""
    for method, url, kwargs in _PROBES:
        response = await client.request(method, url, **kwargs)
        assert response.status_code == 401, f"{method} {url} → {response.status_code}: {response.text}"


@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.transporter])
async def test_viewer_and_transporter_cannot_reach_backups(
    client: AsyncClient,
    session: AsyncSession,
    backups_dir: Path,
    role: UserRole,
) -> None:
    """Зритель и транспортировщик — 403: бэкапы им не раздел, а не «только чтение»."""
    _, headers = await user_headers(session, role, f"backups_{role.value}")
    for method, url, kwargs in _PROBES:
        response = await client.request(method, url, headers=headers, **kwargs)
        assert response.status_code == 403, f"{role.value}: {method} {url} → {response.status_code}"


async def test_admin_passes_backups_gate(
    client: AsyncClient,
    session: AsyncSession,
    backups_dir: Path,
) -> None:
    """Admin проходит гейт: список и конфиг отвечают, скачивание доходит до 404."""
    _, headers = await user_headers(session, UserRole.admin, "backups_admin")

    listing = await client.get("/api/backups", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    config = await client.get("/api/backups/config", headers=headers)
    assert config.status_code == 200, config.text
    assert config.json()["auto_enabled"] is False

    missing = await client.get(
        "/api/backups/backup_ktm2000_test_2026-01-01_10-00-00.zip/download",
        headers=headers,
    )
    assert missing.status_code == 404, missing.text
