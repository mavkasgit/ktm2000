import enum

from sqlalchemy import Boolean, Enum, Float, Integer, String, text, BigInteger, Identity, ARRAY, ForeignKey, CheckConstraint
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
    length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_per_meter: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_per_hanger: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cross_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_thumb: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_full: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_catalog_item: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    is_paired_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)

    # Processing flags
    skip_shot_blast: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    is_laminated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)

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
        CheckConstraint("length_mm > 0", name="ck_product_lengths_positive"),
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
