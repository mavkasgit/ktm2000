"""FastAPI Depends для доступа к PlantConfig (ADR-0004, секция 5).

Только composition root (route handler) резолвит PlantConfig через Depends.
Сервисы получают суб-канон или данные как параметр.
"""

from __future__ import annotations

from fastapi import Request

from app.seeds.canon.models import DisplayCanon, PlantConfig


def get_plant_config(request: Request) -> PlantConfig:
    """Depends: возвращает PlantConfig из app.state (lifespan)."""
    config: PlantConfig = request.app.state.plant_config
    return config


def get_display_config(request: Request) -> DisplayCanon:
    """Depends: возвращает DisplayCanon (суб-канон отображения)."""
    config: PlantConfig = request.app.state.plant_config
    return config.display
