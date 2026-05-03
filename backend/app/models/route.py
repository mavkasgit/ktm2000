from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProductionRoute(Base):
    __tablename__ = "production_routes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    steps: Mapped[list["RouteStep"]] = relationship("RouteStep", back_populates="route", cascade="all, delete-orphan", lazy="selectin")
    rules: Mapped[list["RouteMatchingRule"]] = relationship("RouteMatchingRule", back_populates="route", cascade="all, delete-orphan", lazy="selectin")


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
    conditions: Mapped[list["RouteRuleCondition"]] = relationship("RouteRuleCondition", back_populates="rule", cascade="all, delete-orphan", lazy="selectin")


class RouteRuleCondition(Base):
    __tablename__ = "route_rule_conditions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("route_matching_rules.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    rule: Mapped["RouteMatchingRule"] = relationship("RouteMatchingRule", back_populates="conditions")
