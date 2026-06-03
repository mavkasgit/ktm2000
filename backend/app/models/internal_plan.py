import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Identity, Index, Integer, Numeric, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InternalPlanStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"
    completed = "completed"


class InternalPlan(Base):
    __tablename__ = "internal_plans"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    production_plan_id: Mapped[int] = mapped_column(ForeignKey("production_plans.id"), nullable=False)
    release_batch_id: Mapped[int | None] = mapped_column(ForeignKey("release_batches.id"), nullable=True)
    status: Mapped[InternalPlanStatus] = mapped_column(
        Enum(InternalPlanStatus, name="internal_plan_status"),
        nullable=False,
        server_default=text("'active'"),
        default=InternalPlanStatus.active,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_internal_plans_release_batch", "release_batch_id", unique=True),)


class SectionPlanLine(Base):
    __tablename__ = "section_plan_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    internal_plan_id: Mapped[int] = mapped_column(ForeignKey("internal_plans.id"), nullable=False)
    plan_position_id: Mapped[int] = mapped_column(ForeignKey("plan_positions.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    route_stage_id: Mapped[int] = mapped_column(ForeignKey("route_stages.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cached_available_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_issued_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_completed_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_transferred_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)

    __table_args__ = (
        UniqueConstraint("internal_plan_id", "plan_position_id", "route_stage_id", name="uq_section_plan_lines_stage"),
    )
