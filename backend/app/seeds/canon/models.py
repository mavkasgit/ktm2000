"""Типизированные модели канона заводской конфигурации (ADR-0004).

PlantConfig — корневой объект; доменные суб-модели группируют данные
по ответственности. Валидация формы = часть конструирования (pydantic).
"""

from __future__ import annotations

from typing import Annotated, Literal

from app.models.user import UserRole
from pydantic import BaseModel, Field, field_validator


# ─── Display canon ────────────────────────────────────────────────────────────


class ColorToken(BaseModel):
    """Токен извлечения цвета при импорте."""

    token: str = Field(min_length=1)
    color: str = Field(min_length=1)


class LabelsCanon(BaseModel):
    """Тексты ошибок валидации и прочие UI-лейблы."""

    error_messages: dict[str, str] = Field(default_factory=dict)
    status_labels: dict[str, str] = Field(default_factory=dict)
    output_kind_labels: dict[str, str] = Field(default_factory=dict)
    warning_labels: dict[str, str] = Field(default_factory=dict)
    validation_labels: dict[str, str] = Field(default_factory=dict)
    task_status_labels: dict[str, str] = Field(default_factory=dict)
    stage_status_labels: dict[str, str] = Field(default_factory=dict)
    bulk_status_labels: dict[str, str] = Field(default_factory=dict)
    action_labels: dict[str, str] = Field(default_factory=dict)
    error_phrase_translations: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "error_messages",
        "status_labels",
        "output_kind_labels",
        "warning_labels",
        "validation_labels",
        "task_status_labels",
        "stage_status_labels",
        "bulk_status_labels",
        "action_labels",
        "error_phrase_translations",
    )
    @classmethod
    def _keys_non_empty(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if not key.strip():
                raise ValueError("label key must not be blank")
        return v


class ColorsCanon(BaseModel):
    """Канон цветовых токенов завода."""

    tokens: list[ColorToken] = Field(default_factory=list)

    @field_validator("tokens")
    @classmethod
    def _no_duplicate_tokens(cls, v: list[ColorToken]) -> list[ColorToken]:
        seen: set[str] = set()
        for item in v:
            if item.token in seen:
                raise ValueError(f"Duplicate color token: {item.token!r}")
            seen.add(item.token)
        return v


class RoleDef(BaseModel):
    """Определение роли: код, подпись, разделы навигации (тикет #26)."""

    code: UserRole
    label: str = Field(min_length=1)
    sections: list[str] = Field(default_factory=list)


class RolesCanon(BaseModel):
    """Каталог ролей (тикет #26)."""

    roles: list[RoleDef] = Field(default_factory=list)


class DisplayCanon(BaseModel):
    """Всё, что связано с отображением: лейблы, цвета, роли."""

    colors: ColorsCanon = Field(default_factory=ColorsCanon)
    labels: LabelsCanon = Field(default_factory=LabelsCanon)
    roles: RolesCanon = Field(default_factory=RolesCanon)


# ─── Production canon ─────────────────────────────────────────────────────────


class HangerRoundingRule(BaseModel):
    """Правило округления количества до подвески."""

    enabled: bool = True
    mode: Literal["round_up_to_multiple"] = "round_up_to_multiple"


class ProcessingFlags(BaseModel):
    """Значения признаков обработки техкарт."""

    paired: str = Field(min_length=1)
    standart: str = Field(min_length=1)


class SectionDef(BaseModel):
    """Определение участка (тикет #23)."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    sort_order: int = 0
    type: str = Field(min_length=1)
    icon: str | None = None
    icon_color: str | None = None
    is_active: bool = True


class OperationDef(BaseModel):
    """Определение операции участка (тикет #23)."""

    section_code: str = Field(min_length=1)
    group_code: str | None = None
    group_name: str | None = None
    sort_order: int = 0
    operation_code: str | None = None
    operation_name: str = Field(min_length=1)
    is_significant: bool = False
    icon: str | None = None
    icon_color: str | None = None
    resolver_type: str | None = None
    resolver_config: dict = Field(default_factory=dict)
    operation_type: Literal["production", "transport"] = "production"


class TransformingOpRef(BaseModel):
    """Ссылка на операцию, трансформирующую габариты (тикет #23)."""

    section_code: str = Field(min_length=1)
    operation_code: str = Field(min_length=1)

    def __hash__(self) -> int:
        return hash((self.section_code, self.operation_code))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransformingOpRef):
            return NotImplemented
        return (self.section_code, self.operation_code) == (
            other.section_code,
            other.operation_code,
        )


class ScrapPolicy(BaseModel):
    """Политика брака: параметры SCRAP-секции (тикет #25)."""

    code: str = "SCRAP"
    name: str = "Scrap"
    section_type: str = "scrap"
    sort_order: int = 999


class StockLocationTypes(BaseModel):
    """Типы складских секций (тикет #25)."""

    raw_stock: str = "raw_stock"
    wip_stock: str = "wip_stock"
    finished_stock: str = "finished_stock"
    scrap: str = "scrap"


class ProductionCanon(BaseModel):
    """Производственные политики: участки, операции, подвески, обработка."""

    hanger_rounding: HangerRoundingRule = Field(default_factory=HangerRoundingRule)
    processing_flags: ProcessingFlags
    sections: list[SectionDef] = Field(default_factory=list)
    ops: list[OperationDef] = Field(default_factory=list)
    transforming_ops: list[TransformingOpRef] = Field(default_factory=list)
    scrap_policy: ScrapPolicy = Field(default_factory=ScrapPolicy)
    stock_location_types: StockLocationTypes = Field(default_factory=StockLocationTypes)


# ─── Routing canon (тикет #24) ────────────────────────────────────────────────

ConditionSource = Literal["excel", "payload", "product", "ctx"]
ConditionOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "in",
    "not_in",
    "empty",
    "not_empty",
    "regex",
]
RulePhase = Literal["normalize", "route_select", "resolve_operations", "resolve_signatures"]
RuleActionKind = Literal[
    "require_section",
    "exclude_section",
    "set_operation",
    "set_operation_by_mapping",
    "resolve_by_type",
    "set_field",
    "set_field_from_color_extraction",
    "set",
    "add",
    "remove",
]


class RuleCondition(BaseModel):
    """Условие правила выбора маршрута (тикет #24)."""

    source: ConditionSource = "payload"
    field_path: str = Field(min_length=1)
    excel_column_index: int | None = None
    excel_column_letter: str | None = None
    excel_header: str | None = None
    operator: ConditionOperator
    value: str | bool | None = None
    case_sensitive: bool = False


class SectionActionBase(BaseModel):
    """База действий, ссылающихся на участок по section_code."""

    section_code: str = Field(min_length=1)


class RequireSectionAction(SectionActionBase):
    """Требовать участок в маршруте."""

    action: Literal["require_section"] = "require_section"


class ExcludeSectionAction(SectionActionBase):
    """Исключить участок из маршрута."""

    action: Literal["exclude_section"] = "exclude_section"


class SetOperationAction(BaseModel):
    """Задать конкретную операцию группе участка."""

    action: Literal["set_operation"] = "set_operation"
    section_code: str = Field(min_length=1)
    group_code: str = Field(min_length=1)
    operation_code: str = Field(min_length=1)


class SetOperationByMappingAction(BaseModel):
    """Разрешить операцию по keyword-маппингу из значения поля."""

    action: Literal["set_operation_by_mapping"] = "set_operation_by_mapping"
    section_code: str = Field(min_length=1)
    group_code: str = Field(min_length=1)
    lookup_field: str = Field(min_length=1)
    mapping: list[dict[str, str]] = Field(default_factory=list)


class ResolveByTypeAction(BaseModel):
    """Разрешить операцию по типу позиции."""

    action: Literal["resolve_by_type"] = "resolve_by_type"
    section_code: str = Field(min_length=1)
    group_code: str = Field(min_length=1)


class SetFieldAction(BaseModel):
    """Установить значение поля в payload/ctx."""

    action: Literal["set_field"] = "set_field"
    path: str = Field(min_length=1)
    value: str | bool | None = None


class SetFieldFromColorExtractionAction(BaseModel):
    """Извлечь цвет из source_field и записать в target_field."""

    action: Literal["set_field_from_color_extraction"] = "set_field_from_color_extraction"
    target_field: str = Field(min_length=1)
    source_field: str = Field(min_length=1)


class DslAction(BaseModel):
    """DSL-действие над контекстом (set/add/remove по пути ctx.*)."""

    action: Literal["set", "add", "remove"]
    path: str = Field(min_length=1)
    value: str | bool | None = None


RuleAction = Annotated[
    RequireSectionAction
    | ExcludeSectionAction
    | SetOperationAction
    | SetOperationByMappingAction
    | ResolveByTypeAction
    | SetFieldAction
    | SetFieldFromColorExtractionAction
    | DslAction,
    Field(discriminator="action"),
]


class SelectionRuleDef(BaseModel):
    """Определение правила выбора маршрута (тикет #24)."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    profile_code: str = Field(min_length=1)
    priority: int = Field(ge=0)
    is_active: bool = True
    phase: RulePhase = "route_select"
    conditions: list[RuleCondition] = Field(default_factory=list)
    condition_logic: Literal["and", "or"] = "and"
    actions: list[RuleAction] = Field(default_factory=list)


class ExcelColumnDef(BaseModel):
    """Определение колонки Excel-паспорта."""

    index: int = Field(gt=0)
    header: str = Field(min_length=1)
    letter: str = Field(min_length=1)
    field_path: str = Field(min_length=1)


class RouteRuleProfileDef(BaseModel):
    """Определение профиля правил маршрутизации (тикет #24)."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    is_active: bool = True
    priority: int = Field(ge=0, default=0)
    route_name_pattern: str | None = None
    import_template_code: str | None = None
    route_sections: list[str] = Field(default_factory=list)
    excel_column_passport: list[ExcelColumnDef] = Field(default_factory=list)
    excel_passport_meta: dict = Field(default_factory=dict)


class SPGDef(BaseModel):
    """Определение Storage Production Group (тикет #24)."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    storage_kind: str | None = None
    sort_order: int = 0
    icon: str | None = None
    icon_color: str | None = None
    section_codes: list[str] = Field(default_factory=list)


class RoutingCanon(BaseModel):
    """Правила выбора маршрутов, профили, SPG."""

    selection_rules: list[SelectionRuleDef] = Field(default_factory=list)
    route_rule_profiles: list[RouteRuleProfileDef] = Field(default_factory=list)
    spgs: list[SPGDef] = Field(default_factory=list)


# ─── Quality canon (тикет #25) ────────────────────────────────────────────────


class DefectDecisionDef(BaseModel):
    """Решение по браку → итоговый статус и причина stock-операции."""

    status: str = Field(min_length=1)
    reason: str | None = None


class DefectDecisionMap(BaseModel):
    """Карта решений по браку: decision_code → (status, reason)."""

    mapping: dict[str, DefectDecisionDef] = Field(default_factory=dict)


class DefectTypeDef(BaseModel):
    """Определение типа брака (тикет #25)."""

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str | None = None
    severity: int = Field(ge=1, default=1)
    requires_quality_decision: bool = False
    is_active: bool = True
    description: str | None = None


class QualityCanon(BaseModel):
    """Карта брака и решения по дефектам."""

    defect_decision_map: DefectDecisionMap = Field(default_factory=DefectDecisionMap)
    defect_types: list[DefectTypeDef] = Field(default_factory=list)


# ─── Root ─────────────────────────────────────────────────────────────────────


class PlantConfig(BaseModel):
    """Корневой типизированный объект заводской конфигурации.

    Не может существовать в невалидном виде — pydantic гарантирует
    форму при конструировании, cross-ref проверки в registry.
    """

    production: ProductionCanon
    routing: RoutingCanon = Field(default_factory=RoutingCanon)
    quality: QualityCanon = Field(default_factory=QualityCanon)
    display: DisplayCanon = Field(default_factory=DisplayCanon)
