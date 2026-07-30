import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
        CheckConstraint("planned_quantity >= 0", name="planned_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    section_plan_line_id: Mapped[int] = mapped_column(ForeignKey("section_plan_lines.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    route_stage_id: Mapped[int] = mapped_column(ForeignKey("route_stages.id"), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    # Операция трансформирующего этапа (ADR-0002): вход (количество ×
    # входной габарит) и список выходов [{row_number, quantity, dimensions}]
    # из позиции плана. На нетрансформирующих этапах поля пусты.
    input_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    input_dimensions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outputs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    status: Mapped[WorkTaskStatus] = mapped_column(Enum(WorkTaskStatus, name="work_task_status"), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    selected_operation_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
