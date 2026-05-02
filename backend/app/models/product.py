import enum

from sqlalchemy import Boolean, Enum, Float, Integer, String, text, BigInteger, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductType(str, enum.Enum):
    finished_good = "finished_good"
    semi_finished = "semi_finished"
    component = "component"
    material = "material"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[ProductType] = mapped_column(Enum(ProductType, name="product_type"), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'pcs'"), default="pcs")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Profile-specific fields for aluminum catalog
    profile_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    alloy: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    anod_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_per_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_per_hanger: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cross_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_thumb: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_full: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_catalog_item: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
