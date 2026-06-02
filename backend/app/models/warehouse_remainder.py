from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WarehouseRemainder(Base):
    """Stores surplus quantities returned to stock after task completion.

    When a task is completed with issued > completed, the excess quantity
    is recorded here with information about which stages were completed,
    so it can be reused in future issues.

    Quantity can go negative when manual operations issue more than the
    available stock — this is allowed so users can fix shortages post-factum.
    """
    __tablename__ = "warehouse_remainders"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    route_step_id: Mapped[int | None] = mapped_column(ForeignKey("route_steps.id"), nullable=True)
    section_plan_line_id: Mapped[int | None] = mapped_column(ForeignKey("section_plan_lines.id"), nullable=True)
    origin_task_id: Mapped[int | None] = mapped_column(ForeignKey("work_tasks.id"), nullable=True)
    remainder_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"))
    original_issued: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    completed_stages_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'task'"), default="task")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_task_id: Mapped[int | None] = mapped_column(ForeignKey("work_tasks.id"), nullable=True)
