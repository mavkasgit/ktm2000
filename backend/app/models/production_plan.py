import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Identity, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductionPlanStatus(str, enum.Enum):
    draft = "draft"
    validated = "validated"
    approved = "approved"
    partially_released = "partially_released"
    released = "released"
    cancelled = "cancelled"


class PlanSourceType(str, enum.Enum):
    manual = "manual"
    excel_import = "excel_import"
    api = "api"
    integration = "integration"


class PlanPositionStatus(str, enum.Enum):
    draft = "draft"
    invalid = "invalid"
    valid = "valid"
    approved = "approved"
    released = "released"
    cancelled = "cancelled"


class PlanPositionValidationStatus(str, enum.Enum):
    pending = "pending"
    valid = "valid"
    invalid = "invalid"


class PlanChangeSetStatus(str, enum.Enum):
    draft = "draft"
    applied = "applied"
    cancelled = "cancelled"


class PlanChangeAction(str, enum.Enum):
    create_position = "create_position"
    update_draft_position = "update_draft_position"
    mark_possible_duplicate = "mark_possible_duplicate"
    ignore_unchanged = "ignore_unchanged"
    cancel_draft_position = "cancel_draft_position"


class PlanChangeItemStatus(str, enum.Enum):
    pending = "pending"
    warning = "warning"
    invalid = "invalid"
    applied = "applied"


class ProductionPlan(Base):
    __tablename__ = "production_plans"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    plan_no: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProductionPlanStatus] = mapped_column(
        Enum(ProductionPlanStatus, name="production_plan_status"),
        nullable=False,
        server_default=text("'draft'"),
        default=ProductionPlanStatus.draft,
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlanPosition(Base):
    __tablename__ = "plan_positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    production_plan_id: Mapped[int] = mapped_column(ForeignKey("production_plans.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    source_type: Mapped[PlanSourceType] = mapped_column(Enum(PlanSourceType, name="plan_source_type"), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_plan_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    source_sku: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    customer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("100"), default=100)
    source_row_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[PlanPositionStatus] = mapped_column(Enum(PlanPositionStatus, name="plan_position_status"), nullable=False)
    validation_status: Mapped[PlanPositionValidationStatus] = mapped_column(
        Enum(PlanPositionValidationStatus, name="plan_position_validation_status"),
        nullable=False,
    )
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_plan_positions_import_row", "import_batch_id", "source_row_number", unique=True),
        Index("ix_plan_positions_import_hash", "import_batch_id", "source_row_hash", unique=True),
    )


class PlanChangeSet(Base):
    __tablename__ = "plan_change_sets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    production_plan_id: Mapped[int] = mapped_column(ForeignKey("production_plans.id"), nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    status: Mapped[PlanChangeSetStatus] = mapped_column(
        Enum(PlanChangeSetStatus, name="plan_change_set_status"),
        nullable=False,
        server_default=text("'draft'"),
        default=PlanChangeSetStatus.draft,
    )
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlanChangeItem(Base):
    __tablename__ = "plan_change_items"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    change_set_id: Mapped[int] = mapped_column(ForeignKey("plan_change_sets.id"), nullable=False)
    plan_position_id: Mapped[int | None] = mapped_column(ForeignKey("plan_positions.id"), nullable=True)
    source_row_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_action: Mapped[PlanChangeAction] = mapped_column(Enum(PlanChangeAction, name="plan_change_action"), nullable=False)
    before_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[PlanChangeItemStatus] = mapped_column(Enum(PlanChangeItemStatus, name="plan_change_item_status"), nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_plan_change_items_change_set", "change_set_id"),)
