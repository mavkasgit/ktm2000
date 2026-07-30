from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Identity, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DimensionType(Base):
    """Справочник измерений: допустимые ключи dimensions (ADR-0001, п. 3)."""

    __tablename__ = "dimension_types"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    value_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'number'"), default="number")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    product_links: Mapped[list["ProductDimension"]] = relationship(
        "ProductDimension", back_populates="dimension_type", cascade="all, delete-orphan"
    )


class ProductDimension(Base):
    """Привязка измерения к продукту: обязательность + типовой размер (default_value)."""

    __tablename__ = "product_dimensions"
    __table_args__ = (
        UniqueConstraint("product_id", "dimension_type_id", name="uq_product_dimensions_product_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimension_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dimension_types.id"), nullable=False
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    default_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    dimension_type: Mapped["DimensionType"] = relationship("DimensionType", back_populates="product_links")
