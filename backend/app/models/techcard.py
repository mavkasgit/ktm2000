from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Numeric, String, Boolean, text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Techcard(Base):
    __tablename__ = "techcards"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    processing_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'standart_processing'"),
        default="standart_processing",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        Index("ix_techcards_active_one_per_product", "product_id", unique=True, postgresql_where=text("is_active = true")),
    )


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


class TechcardPair(Base):
    __tablename__ = "techcard_pairs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    techcard_id: Mapped[int] = mapped_column(ForeignKey("techcards.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("100"), default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class TechcardPairLine(Base):
    __tablename__ = "techcard_pair_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    techcard_pair_id: Mapped[int] = mapped_column(ForeignKey("techcard_pairs.id"), nullable=False)
    component_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("techcard_pair_id", "component_product_id", name="uq_techcard_pair_lines_component"),
    )
