import enum
import re
from typing import Any

from sqlalchemy import Boolean, Enum, Float, Integer, String, text, BigInteger, Identity, ARRAY, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

_NUMERIC_KEY_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _length_key(length_mm: float) -> str:
    """Canonical JSONB dict key for a length in mm (whole numbers without .0)."""
    value = float(length_mm)
    return str(int(value)) if value.is_integer() else str(value)


def _is_numeric_key(key: str) -> bool:
    return bool(_NUMERIC_KEY_RE.match(str(key)))


def _normalize_entry(value: Any) -> dict[str, int | None]:
    """Нормализует значение длины в {auto: int|null, manual: int|null}."""
    if not isinstance(value, dict):
        return {"auto": None, "manual": None}
    auto = value.get("auto")
    manual = value.get("manual")
    return {
        "auto": int(auto) if isinstance(auto, int) else None,
        "manual": int(manual) if isinstance(manual, int) else None,
    }


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
    # quantity_per_hanger (#60) — dict {length_mm: {"auto": int|null, "manual": int|null}}
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
    def perimeter_mm(self) -> float | None:
        """Периметр сечения профиля, мм (авто-поле расчёта #60). Плоское поле в API."""
        return (self.attributes or {}).get("perimeter_mm")

    @perimeter_mm.setter
    def perimeter_mm(self, value: float | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("perimeter_mm", None)
        else:
            attrs["perimeter_mm"] = value
        self.attributes = attrs

    @property
    def mount_width_mm(self) -> float | None:
        """Габарит профиля, мм (авто-поле расчёта #60). Плоское поле в API."""
        return (self.attributes or {}).get("mount_width_mm")

    @mount_width_mm.setter
    def mount_width_mm(self, value: float | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("mount_width_mm", None)
        else:
            attrs["mount_width_mm"] = value
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

    def _hanger_dict(self) -> dict[str, Any] | None:
        """Raw quantity_per_hanger dict or None (bare {auto, manual} allowed)."""
        d = (self.attributes or {}).get("quantity_per_hanger")
        return d if isinstance(d, dict) else None

    def _primary_hanger_length_key(self) -> str | None:
        """Min numeric length key of the per-length dict, or None for bare dicts."""
        d = self._hanger_dict()
        if not d:
            return None
        numeric = [k for k in d if _is_numeric_key(k)]
        if not numeric:
            return None
        return _length_key(min(float(k) for k in numeric))

    @property
    def quantity_per_hanger(self) -> int | None:
        """Эффективное значение для основной длины: авто > ручное, legacy-скаляр.

        Обратная совместимость для потребителей, которым нужен один скаляр
        (план-импорт, ZIP-импорт, старые тесты). Каноническое per-length
        представление — :attr:`quantity_per_hanger_by_length`.
        """
        d = self._hanger_dict()
        if d is None:
            raw = (self.attributes or {}).get("quantity_per_hanger")
            return raw if isinstance(raw, int) else None
        key = self._primary_hanger_length_key()
        entry = d.get(key) if key is not None else d
        if not isinstance(entry, dict):
            return None
        auto = entry.get("auto")
        manual = entry.get("manual")
        if auto is not None:
            return int(auto)
        return int(manual) if manual is not None else None

    @quantity_per_hanger.setter
    def quantity_per_hanger(self, value: int | dict | None) -> None:
        """Setter принимает per-length dict или legacy-скаляр.

        Legacy-скаляр хранится как bare ``{auto: null, manual: value}`` и
        нормализуется в per-length эндпоинтом, когда длины уже известны.
        """
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("quantity_per_hanger", None)
        elif isinstance(value, dict):
            attrs["quantity_per_hanger"] = {
                _length_key(float(k)): _normalize_entry(v)
                for k, v in value.items()
                if isinstance(v, dict)
            }
        else:
            # Legacy scalar — bare {auto: null, manual: value}; endpoint
            # normalizes to per-length once lengths are known.
            attrs["quantity_per_hanger"] = {"auto": None, "manual": int(value)}
        self.attributes = attrs

    @property
    def quantity_per_hanger_by_length(self) -> dict[str, dict[str, int | None]] | None:
        """Per-length quantity_per_hanger: {length_mm: {"auto": int|null, "manual": int|null}}."""
        d = self._hanger_dict()
        if not d:
            return None
        has_numeric_keys = any(_is_numeric_key(k) for k in d)
        if not has_numeric_keys:
            # Bare {auto, manual} (legacy-скаляр) — раскрываем под основную длину.
            lengths = sorted([l.length_mm for l in self.lengths]) if self.lengths else []
            if not lengths:
                return None
            return {_length_key(lengths[0]): _normalize_entry(d)}
        normalized = {
            _length_key(float(k)): _normalize_entry(v)
            for k, v in d.items()
            if isinstance(v, dict)
        }
        return normalized or None

    def quantity_per_hanger_for_length(self, length_mm: float) -> int | None:
        """Эффективное значение на подвес для конкретной длины: авто > ручное."""
        d = self._hanger_dict()
        if d is None:
            raw = (self.attributes or {}).get("quantity_per_hanger")
            return raw if isinstance(raw, int) else None
        entry = d.get(_length_key(length_mm))
        if not isinstance(entry, dict):
            # Bare dict без ключа длины (legacy-скаляр) — берём manual.
            if not _is_numeric_key(next(iter(d), "")):
                entry = d
            else:
                return None
        if not isinstance(entry, dict):
            return None
        auto = entry.get("auto")
        manual = entry.get("manual")
        if auto is not None:
            return int(auto)
        return int(manual) if manual is not None else None

    def main_quantity_per_hanger(self) -> int | None:
        """Скаляр для обратной совместимости: значение для основной длины.

        Основная длина — минимальный числовой ключ per-length dict (первая
        длина из ProductLength по возрастанию). Без обращения к relationship
        (безопасно в async). Используется потребителями, которым нужен один
        скаляр (например, план-импорт до интеграции #66).
        """
        return self.quantity_per_hanger

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
