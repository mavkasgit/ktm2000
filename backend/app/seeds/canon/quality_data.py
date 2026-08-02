"""Данные QualityCanon, авторятся конструкторами моделей (ADR-0004, тикет #25).

Карта решений по браку и справочник типов брака. Это данные завода
(меняются релизом), не логика сервиса.
"""

from __future__ import annotations

from app.seeds.canon.models import (
    DefectDecisionDef,
    DefectDecisionMap,
    DefectTypeDef,
)

# Решение по браку → (итоговый статус Defect, причина stock-операции Reason).
# Ключи — значения DefectDecisionType, status — DefectStatus, reason — Reason.
DEFECT_DECISION_MAP = DefectDecisionMap(
    mapping={
        "scrap": DefectDecisionDef(status="scrapped", reason="scrap"),
        "rework_current": DefectDecisionDef(
            status="rework_task_created", reason="rework"
        ),
        "return_previous": DefectDecisionDef(
            status="rework_task_created", reason="return_to_previous"
        ),
        "accept_with_deviation": DefectDecisionDef(
            status="accepted_with_deviation", reason="complete"
        ),
    }
)

# Справочник типов брака (таблица defect_types, редактируется админом через UI).
DEFECT_TYPES = [
    DefectTypeDef(
        code="SCRATCH",
        name="Царапина",
        category="surface",
        severity=2,
        description="Поверхностные царапины и следы обработки",
    ),
    DefectTypeDef(
        code="DENT",
        name="Вмятина",
        category="geometry",
        severity=3,
        description="Вмятины и деформации профиля",
    ),
    DefectTypeDef(
        code="SHADE",
        name="Оттенок",
        category="anodizing",
        severity=2,
        requires_quality_decision=True,
        description="Несоответствие оттенка анодирования",
    ),
    DefectTypeDef(
        code="ANOD_FILM",
        name="Дефект анодного покрытия",
        category="anodizing",
        severity=3,
        requires_quality_decision=True,
        description="Неравномерность или дефект анодной плёнки",
    ),
    DefectTypeDef(
        code="DIMENSION",
        name="Несоответствие размеров",
        category="geometry",
        severity=4,
        requires_quality_decision=True,
        description="Отклонение геометрических размеров",
    ),
    DefectTypeDef(
        code="SURFACE",
        name="Дефект поверхности",
        category="surface",
        severity=2,
        description="Прочие дефекты поверхности",
    ),
]
