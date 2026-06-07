from datetime import datetime
from enum import Enum
from typing import Any
from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    CANCEL = "cancel"
    RESTORE = "restore"
    IMPORT = "import"
    SEND = "send"
    RECEIVE = "receive"
    CORRECT = "correct"
    RELEASE = "release"


class AuditEntityType(str, Enum):
    PRODUCT = "product"
    SECTION = "section"
    ROUTE = "route"
    TECHCARD = "techcard"
    PRODUCTION_PLAN = "production_plan"
    PLAN_POSITION = "plan_position"
    WORK_TASK = "work_task"
    TRANSFER = "transfer"
    TRANSFER_DISCREPANCY = "transfer_discrepancy"
    DEFECT = "defect"
    DEFECT_ITEM = "defect_item"
    DEFECT_DECISION = "defect_decision"
    REWORK_TASK = "rework_task"
    IMPORT_BATCH = "import_batch"
    USER = "user"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Пользователь, совершивший действие
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Информация события
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "success" | "error" | "info"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Структурированные поля для логирования сущностей и диффов
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Мягкая связь с участком
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Денормализованные контекстные поля
    task_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qty_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)

