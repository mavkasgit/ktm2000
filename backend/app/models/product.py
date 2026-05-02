import enum

from sqlalchemy import Boolean, Enum, String, text, BigInteger, Identity
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
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[ProductType] = mapped_column(Enum(ProductType, name="product_type"), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
