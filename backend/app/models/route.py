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
    norm_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    route: Mapped["ProductionRoute"] = relationship("ProductionRoute", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_steps_sequence"),
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
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_at: Mapped[None] = mapped_column(DateTime, server_default=func.now())
