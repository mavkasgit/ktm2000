from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductionRoute(Base):
    __tablename__ = "production_routes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        Index(
            "ix_routes_active_one_per_product",
            "product_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )


class RouteStep(Base):
    __tablename__ = "route_steps"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("production_routes.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    norm_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_steps_sequence"),
    )
