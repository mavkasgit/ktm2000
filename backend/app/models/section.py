from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# Префикс упаковочных операций. Колонка «Упаковка» (доска участка и лист
# печати) применима только к участкам, у которых такая операция есть в
# справочнике (`app/seeds/sections.py`: ANODIZING — PACK_STRETCH/PACK_SPUNBOND,
# PACKING — PACK/PACK_GLUE/PACK_LENS; у SAWING только SAW*). Тот же префикс
# считает значение ячейки на фронте (`lib/taskView.ts`,
# PACKAGING_OPERATION_PREFIX): разойдись они — колонка либо исчезнет вместе
# с данными, либо останется на участке, где упаковки не бывает.
PACKAGING_OPERATION_PREFIX = "PACK"


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
    type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default="production", server_default=text("'production'"),
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # «Склад выпуска» (#137): адресат FINAL_RELEASE по умолчанию, когда
    # за финальным этапом маршрута не следует транзитный хоп. Ровно одна
    # секция в каталоге; несколько → резолв отказывает (не молчаливый выбор).
    is_output_default: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    legacy_users = relationship("User", back_populates="section")
    users = relationship("User", secondary="user_sections", back_populates="sections", lazy="selectin")
    operations = relationship("SectionOperation", back_populates="section", cascade="all, delete-orphan", lazy="selectin")
    spg_links = relationship("StorageProductionGroup", secondary="spg_sections", back_populates="sections", lazy="selectin")

    @property
    def operations_count(self) -> int:
        return len(self.operations)

    @property
    def spg_id(self) -> int | None:
        return self.spg_links[0].id if self.spg_links else None

    @property
    def has_packaging(self) -> bool:
        """Есть ли у участка упаковочные операции (префикс — константа выше).

        Читается по `operations`: relationship объявлен `lazy="selectin"`,
        то есть операции уже загружены вместе с участком — отдельного запроса
        и скрытого lazy-load здесь нет. Отдаётся фронту в `SectionOut`; по
        нему доска участка и лист печати скрывают колонку «Упаковка».
        """
        return any(
            (operation.operation_code or "").startswith(PACKAGING_OPERATION_PREFIX)
            for operation in self.operations
        )

