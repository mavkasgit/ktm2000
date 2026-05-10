import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Identity, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DefectStatus(str, enum.Enum):
    open = "open"
    decision_required = "decision_required"
    rework_task_created = "rework_task_created"
    scrapped = "scrapped"
    returned = "returned"
    accepted_with_deviation = "accepted_with_deviation"
    closed = "closed"


class DefectDecisionType(str, enum.Enum):
    scrap = "scrap"
    rework_current = "rework_current"
    return_previous = "return_previous"
    quality_hold = "quality_hold"
    accept_with_deviation = "accept_with_deviation"


class DefectType(Base):
    __tablename__ = "defect_types"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"), default=1)
    requires_quality_decision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Defect(Base):
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), nullable=False)
    movement_id: Mapped[int | None] = mapped_column(ForeignKey("movements.id"), nullable=True)
    status: Mapped[DefectStatus] = mapped_column(
        Enum(DefectStatus, name="defect_status"),
        nullable=False,
        server_default=text("'open'"),
        default=DefectStatus.open,
    )
    responsible_section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DefectItem(Base):
    __tablename__ = "defect_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_defect_items_qty_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    defect_id: Mapped[int] = mapped_column(ForeignKey("defects.id"), nullable=False)
    defect_type_id: Mapped[int | None] = mapped_column(ForeignKey("defect_types.id"), nullable=True)
    defect_type_code_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    defect_type_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subtype_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DefectDecision(Base):
    __tablename__ = "defect_decisions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_defect_decisions_qty_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    defect_id: Mapped[int] = mapped_column(ForeignKey("defects.id"), nullable=False)
    decision_type: Mapped[DefectDecisionType] = mapped_column(
        Enum(DefectDecisionType, name="defect_decision_type"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    target_section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TransferDiscrepancyDefectItem(Base):
    __tablename__ = "transfer_discrepancy_defect_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_discrepancy_defect_item_qty_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    transfer_discrepancy_id: Mapped[int] = mapped_column(ForeignKey("transfer_discrepancies.id"), nullable=False)
    defect_item_id: Mapped[int] = mapped_column(ForeignKey("defect_items.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
