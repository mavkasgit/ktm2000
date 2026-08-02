"""FastAPI Depends для доступа к PlantConfig (ADR-0004, секция 5).

Только composition root (route handler) резолвит PlantConfig через Depends.
Сервисы получают суб-канон или данные как параметр.
"""

from __future__ import annotations

from fastapi import Request

from app.seeds.canon.models import DisplayCanon, PlantConfig


def _resolve(request: Request) -> PlantConfig:
    """PlantConfig из app.state; ленивая сборка, если lifespan не отработал (тесты)."""
    config = getattr(request.app.state, "plant_config", None)
    if config is None:
        from app.seeds.canon.registry import build_plant_config

        config = build_plant_config()
        request.app.state.plant_config = config
    return config


def get_plant_config(request: Request) -> PlantConfig:
    """Depends: возвращает PlantConfig из app.state (lifespan)."""
    return _resolve(request)


def get_display_config(request: Request) -> DisplayCanon:
    """Depends: возвращает DisplayCanon (суб-канон отображения)."""
    return _resolve(request).display
