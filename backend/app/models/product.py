import enum
from typing import Any

from sqlalchemy import Boolean, Enum, Float, Integer, String, text, BigInteger, Identity, ARRAY, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    photo_thumb: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_full: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_catalog_item: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    is_paired_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)

    # Flexible attributes JSONB (#19): length_mm, weight_per_meter, quantity_per_hanger, cross_section
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    # ─── Derived accessors for backward compatibility ───────────────────────
    @property
    def length_mm(self) -> float | None:
        return (self.attributes or {}).get("length_mm")

    @length_mm.setter
    def length_mm(self, value: float | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("length_mm", None)
        else:
            attrs["length_mm"] = value
        self.attributes = attrs

    @property
    def weight_per_meter(self) -> float | None:
        return (self.attributes or {}).get("weight_per_meter")

    @weight_per_meter.setter
    def weight_per_meter(self, value: float | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("weight_per_meter", None)
        else:
            attrs["weight_per_meter"] = value
        self.attributes = attrs

    @property
    def quantity_per_hanger(self) -> int | None:
        return (self.attributes or {}).get("quantity_per_hanger")

    @quantity_per_hanger.setter
    def quantity_per_hanger(self, value: int | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("quantity_per_hanger", None)
        else:
            attrs["quantity_per_hanger"] = value
        self.attributes = attrs

    @property
    def cross_section(self) -> str | None:
        return (self.attributes or {}).get("cross_section")

    @cross_section.setter
    def cross_section(self, value: str | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("cross_section", None)
        else:
            attrs["cross_section"] = value
        self.attributes = attrs

    # Equivalent SKU aliases
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default=text("'{}'"), default=list)

    # Relationships
    lengths: Mapped[list["ProductLength"]] = relationship("ProductLength", back_populates="product", cascade="all, delete-orphan")
    processing_flags: Mapped[list["ProcessingFlag"]] = relationship(
        "ProcessingFlag",
        secondary="product_processing_flags",
        back_populates="products",
    )


class ProductLength(Base):
    __tablename__ = "product_lengths"
    __table_args__ = (
        CheckConstraint("length_mm > 0", name="positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    length_mm: Mapped[float] = mapped_column(Float, nullable=False)

    product: Mapped["Product"] = relationship("Product", back_populates="lengths")


class ProcessingFlag(Base):
    __tablename__ = "processing_flags"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    section_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)

    products: Mapped[list["Product"]] = relationship(
        "Product",
        secondary="product_processing_flags",
        back_populates="processing_flags",
    )


class ProductProcessingFlag(Base):
    __tablename__ = "product_processing_flags"

    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), primary_key=True)
    flag_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("processing_flags.id"), primary_key=True)
