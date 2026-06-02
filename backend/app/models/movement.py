import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Identity, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MovementType(str, enum.Enum):
    issue_to_work = "issue_to_work"
    complete = "complete"
    transfer_send = "transfer_send"
    transfer_receive = "transfer_receive"
    reject = "reject"
    scrap = "scrap"
    return_to_previous = "return_to_previous"
    final_release = "final_release"
    adjustment = "adjustment"
    return_to_stock = "return_to_stock"
    manual_in = "manual_in"
    manual_out = "manual_out"


class Movement(Base):
    __tablename__ = "movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_movements_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("work_tasks.id"), nullable=True)
    section_plan_line_id: Mapped[int | None] = mapped_column(ForeignKey("section_plan_lines.id"), nullable=True)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id"), nullable=True)
    from_section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    to_section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType, name="movement_type"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    executor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executor_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
