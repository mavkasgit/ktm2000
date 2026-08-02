"""Типизированный канон сидов завода (ADR-0004).

Публичный интерфейс:
- build_plant_config() — сборка + валидация (единственная точка конструирования)
- get_plant_config / get_display_config — FastAPI Depends
- Модели: PlantConfig, DisplayCanon, ProductionCanon, и т.д.
"""

from app.seeds.canon.dependencies import get_display_config, get_plant_config
from app.seeds.canon.models import (
    ColorToken,
    ColorsCanon,
    DisplayCanon,
    HangerRoundingRule,
    LabelsCanon,
    OperationDef,
    PlantConfig,
    ProcessingFlags,
    ProductionCanon,
    QualityCanon,
    RolesCanon,
    RoutingCanon,
    SectionDef,
    TransformingOpRef,
)
from app.seeds.canon.registry import build_plant_config

__all__ = [
    "ColorToken",
    "ColorsCanon",
    "DisplayCanon",
    "HangerRoundingRule",
    "LabelsCanon",
    "OperationDef",
    "PlantConfig",
    "ProcessingFlags",
    "ProductionCanon",
    "QualityCanon",
    "RolesCanon",
    "RoutingCanon",
    "SectionDef",
    "TransformingOpRef",
    "build_plant_config",
    "get_display_config",
    "get_plant_config",
]
