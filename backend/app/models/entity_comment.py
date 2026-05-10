import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Identity, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EntityType(str, enum.Enum):
    plan_position = "plan_position"
    section_plan_line = "section_plan_line"
    work_task = "work_task"
    transfer = "transfer"
    transfer_discrepancy = "transfer_discrepancy"
    defect = "defect"
    defect_item = "defect_item"
    defect_decision = "defect_decision"
    rework_task = "rework_task"


class EntityComment(Base):
    __tablename__ = "entity_comments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comment_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'note'"), default="note")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
