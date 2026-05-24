from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.routing import RouteOperationFamily, RouteOutputKind


class ProductionRoute(Base):
    __tablename__ = "production_routes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    steps: Mapped[list["RouteStep"]] = relationship("RouteStep", back_populates="route", lazy="selectin")
    rules: Mapped[list["RouteMatchingRule"]] = relationship("RouteMatchingRule", back_populates="route", lazy="selectin")
    signature_rules: Mapped[list["RouteSignatureRule"]] = relationship("RouteSignatureRule", back_populates="route", lazy="selectin")


class RouteStep(Base):
    __tablename__ = "route_steps"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    operation_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_significant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    norm_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    route: Mapped["ProductionRoute"] = relationship("ProductionRoute", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_steps_sequence"),
    )


class SectionOperation(Base):
    __tablename__ = "section_operations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    operation_code: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_significant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    section: Mapped["Section"] = relationship("Section")

    __table_args__ = (
        UniqueConstraint("section_id", "operation_code", name="uq_section_operations"),
    )


class RouteMatchingRule(Base):
    __tablename__ = "route_matching_rules"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[None] = mapped_column(DateTime, server_default=func.now())

    route: Mapped["ProductionRoute"] = relationship("ProductionRoute", back_populates="rules")
    conditions: Mapped[list["RouteRuleCondition"]] = relationship("RouteRuleCondition", back_populates="rule", lazy="selectin")


class RouteRuleCondition(Base):
    __tablename__ = "route_rule_conditions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("route_matching_rules.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    rule: Mapped["RouteMatchingRule"] = relationship("RouteMatchingRule", back_populates="conditions")


class RouteSignatureRule(Base):
    __tablename__ = "route_signature_rules"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    operation_family: Mapped[RouteOperationFamily] = mapped_column(
        Enum(RouteOperationFamily, name="route_operation_family"),
        nullable=False,
    )
    output_kind: Mapped[RouteOutputKind] = mapped_column(
        Enum(RouteOutputKind, name="route_output_kind"),
        nullable=False,
    )
    has_pack_ops: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at: Mapped[None] = mapped_column(DateTime, server_default=func.now())

    route: Mapped["ProductionRoute"] = relationship("ProductionRoute", back_populates="signature_rules")


class RouteSelectionRule(Base):
    __tablename__ = "route_selection_rules"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("route_rule_profiles.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'route_select'"), default="route_select")
    created_at: Mapped[None] = mapped_column(DateTime, server_default=func.now())

    profile: Mapped["RouteRuleProfile | None"] = relationship("RouteRuleProfile", back_populates="rules")


class RouteRuleProfile(Base):
    __tablename__ = "route_rule_profiles"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    import_template_id: Mapped[int | None] = mapped_column(ForeignKey("import_templates.id"), nullable=True)
    excel_column_passport: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    excel_passport_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    created_at: Mapped[None] = mapped_column(DateTime, server_default=func.now())

    rules: Mapped[list["RouteSelectionRule"]] = relationship("RouteSelectionRule", back_populates="profile", lazy="selectin")
    import_template: Mapped["ImportTemplate | None"] = relationship("ImportTemplate")
