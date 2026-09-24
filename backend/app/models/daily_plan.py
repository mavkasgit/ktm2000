from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyPlan(Base):
    __tablename__ = "daily_plans"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (Index("ix_daily_plans_section_plan_date", "section_id", "plan_date"),)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class DailyPlanItem(Base):
    __tablename__ = "daily_plan_items"

    daily_plan_id: Mapped[int] = mapped_column(
        ForeignKey("daily_plans.id", ondelete="CASCADE"), primary_key=True
    )
    work_task_id: Mapped[int] = mapped_column(
        ForeignKey("work_tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        UniqueConstraint("work_task_id", name="uq_daily_plan_items_work_task"),
        Index("ix_daily_plan_items_daily_plan_id", "daily_plan_id"),
    )

