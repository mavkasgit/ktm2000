import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Identity, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReleaseBatchType(str, enum.Enum):
    near_term = "near_term"
    weekly = "weekly"
    future_preparation = "future_preparation"
    manual = "manual"


class ReleaseBatchStatus(str, enum.Enum):
    draft = "draft"
    released = "released"
    cancelled = "cancelled"


class ReleaseBatch(Base):
    __tablename__ = "release_batches"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    production_plan_id: Mapped[int] = mapped_column(ForeignKey("production_plans.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_type: Mapped[ReleaseBatchType] = mapped_column(Enum(ReleaseBatchType, name="release_batch_type"), nullable=False)
    status: Mapped[ReleaseBatchStatus] = mapped_column(
        Enum(ReleaseBatchStatus, name="release_batch_status"),
        nullable=False,
        server_default=text("'draft'"),
        default=ReleaseBatchStatus.draft,
    )
    horizon_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReleaseBatchPosition(Base):
    __tablename__ = "release_batch_positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    release_batch_id: Mapped[int] = mapped_column(ForeignKey("release_batches.id"), nullable=False)
    plan_position_id: Mapped[int] = mapped_column(ForeignKey("plan_positions.id"), nullable=False)
    release_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    route_version: Mapped[str] = mapped_column(String(100), nullable=False)
    route_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)

    __table_args__ = (UniqueConstraint("release_batch_id", "plan_position_id", name="uq_release_batch_position"),)
