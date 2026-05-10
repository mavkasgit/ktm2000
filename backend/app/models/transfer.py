import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, Identity, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TransferStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    partially_accepted = "partially_accepted"
    rejected = "rejected"
    cancelled = "cancelled"


class TransferDiscrepancyStatus(str, enum.Enum):
    open = "open"
    partially_resolved = "partially_resolved"
    resolved = "resolved"
    cancelled = "cancelled"


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("sent_quantity > 0", name="ck_transfers_sent_quantity_positive"),
        CheckConstraint("accepted_quantity IS NULL OR accepted_quantity >= 0", name="ck_transfers_accepted_quantity_non_negative"),
        CheckConstraint("rejected_quantity IS NULL OR rejected_quantity >= 0", name="ck_transfers_rejected_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    from_task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), nullable=False)
    to_task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), nullable=False)
    from_section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    to_section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    sent_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    accepted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    rejected_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus, name="transfer_status"),
        nullable=False,
        server_default=text("'draft'"),
        default=TransferStatus.draft,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TransferDiscrepancy(Base):
    __tablename__ = "transfer_discrepancies"
    __table_args__ = (
        CheckConstraint("discrepancy_quantity > 0", name="ck_transfer_discrepancy_qty_positive"),
        CheckConstraint("resolved_quantity >= 0", name="ck_transfer_discrepancy_resolved_non_negative"),
        CheckConstraint("unresolved_quantity >= 0", name="ck_transfer_discrepancy_unresolved_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("transfers.id"), nullable=False)
    discrepancy_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    resolved_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, server_default=text("0"), default=0)
    unresolved_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[TransferDiscrepancyStatus] = mapped_column(
        Enum(TransferDiscrepancyStatus, name="transfer_discrepancy_status"),
        nullable=False,
        server_default=text("'open'"),
        default=TransferDiscrepancyStatus.open,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
