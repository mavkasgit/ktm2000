import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Identity, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReworkTaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class ReworkTask(Base):
    __tablename__ = "rework_tasks"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_rework_tasks_qty_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    defect_id: Mapped[int] = mapped_column(ForeignKey("defects.id"), nullable=False)
    source_task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[ReworkTaskStatus] = mapped_column(
        Enum(ReworkTaskStatus, name="rework_task_status"),
        nullable=False,
        server_default=text("'open'"),
        default=ReworkTaskStatus.open,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
