from sqlalchemy import BigInteger, ForeignKey, Identity, Numeric, String, Boolean, Integer, text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Techcard(Base):
    __tablename__ = "techcards"
    __table_args__ = (
        Index(
            "ix_techcards_active_one_per_product",
            "product_id",
            unique=True,
            postgresql_where=text("is_active = true AND product_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    processing_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'standart_processing'"),
        default="standart_processing",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    quantity_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_a_per_item: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_b_per_item: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hangers_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hangers_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hangers_total: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TechcardLine(Base):
    __tablename__ = "techcard_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    techcard_id: Mapped[int] = mapped_column(ForeignKey("techcards.id"), nullable=False)
    component_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("techcard_id", "component_product_id", name="uq_techcard_lines_component"),
    )
