from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="production", server_default=text("'production'"))
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    users = relationship("User", back_populates="section")
    operations = relationship("SectionOperation", back_populates="section", cascade="all, delete-orphan", lazy="selectin")
    spg_links = relationship("StorageProductionGroup", secondary="spg_sections", back_populates="sections", lazy="selectin")

    @property
    def operations_count(self) -> int:
        return len(self.operations)
