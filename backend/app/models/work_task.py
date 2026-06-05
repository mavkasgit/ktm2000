import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkTaskStatus(str, enum.Enum):
    waiting_previous = "waiting_previous"
    ready = "ready"
    in_progress = "in_progress"
    partially_completed = "partially_completed"
    completed = "completed"
    cancelled = "cancelled"


class WorkTask(Base):
    __tablename__ = "work_tasks"
    __table_args__ = (
        CheckConstraint("cached_available_quantity >= 0", name="ck_work_tasks_cached_available_quantity_non_negative"),
        CheckConstraint("cached_issued_quantity >= 0", name="ck_work_tasks_cached_issued_quantity_non_negative"),
        CheckConstraint("cached_in_work_quantity >= 0", name="ck_work_tasks_cached_in_work_quantity_non_negative"),
        CheckConstraint("cached_completed_quantity >= 0", name="ck_work_tasks_cached_completed_quantity_non_negative"),
        CheckConstraint("cached_transferred_quantity >= 0", name="ck_work_tasks_cached_transferred_quantity_non_negative"),
        CheckConstraint("cached_received_quantity >= 0", name="ck_work_tasks_cached_received_quantity_non_negative"),
        CheckConstraint("cached_rejected_quantity >= 0", name="ck_work_tasks_cached_rejected_quantity_non_negative"),
        CheckConstraint("cached_remaining_quantity >= 0", name="ck_work_tasks_cached_remaining_quantity_non_negative"),
        CheckConstraint("planned_quantity >= 0", name="ck_work_tasks_planned_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    section_plan_line_id: Mapped[int] = mapped_column(ForeignKey("section_plan_lines.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    route_stage_id: Mapped[int] = mapped_column(ForeignKey("route_stages.id"), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[WorkTaskStatus] = mapped_column(Enum(WorkTaskStatus, name="work_task_status"), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    cached_available_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_issued_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_in_work_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_completed_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_transferred_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    cached_remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    selected_operation_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
