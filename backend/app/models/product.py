import enum
import re
from typing import Any

from sqlalchemy import Boolean, Enum, Float, Integer, String, text, BigInteger, Identity, ARRAY, ForeignKey, CheckConstraint, Index, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.attributes import instance_state

from app.models.base import Base

_NUMERIC_KEY_RE = re.compile(r"^-?\d+(\.\d+)?$")

# Режим подвеса (#126): явное поле auto|manual, хранение в attributes.
HANGER_MODE_AUTO = "auto"
HANGER_MODE_MANUAL = "manual"
HANGER_MODES = (HANGER_MODE_AUTO, HANGER_MODE_MANUAL)


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


class DimensionState(str, enum.Enum):
    length = "length"
    area = "area"
    volume = "volume"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
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
    dimension_state: Mapped[DimensionState] = mapped_column(
        Enum(DimensionState, name="product_dimension_state"),
        nullable=False,
        server_default=text("'length'"),
        default=DimensionState.length,
    )

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
    def hanger_mode(self) -> str:
        """Режим подвеса (#126): 'auto' | 'manual', по умолчанию 'auto'."""
        value = (self.attributes or {}).get("hanger_mode")
        return value if value in HANGER_MODES else HANGER_MODE_AUTO

    @hanger_mode.setter
    def hanger_mode(self, value: str | None) -> None:
        attrs = dict(self.attributes or {})
        if value is None:
            attrs.pop("hanger_mode", None)
        else:
            if value not in HANGER_MODES:
                raise ValueError(f"hanger_mode должен быть одним из {HANGER_MODES}, получено {value!r}")
            attrs["hanger_mode"] = value
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
        """Key длины для основной длины per-length dict, или None для bare dicts.

        Bare-словарь {auto, manual} (legacy-скаляр) возвращает None — caller
        фолбэчит на сам dict, и значение скаляра сохраняется.
        """
        d = self._hanger_dict()
        if not d:
            return None
        numeric = [k for k in d if _is_numeric_key(k)]
        if not numeric:
            return None
        primary = self.primary_length_mm
        if primary is not None:
            key = _length_key(primary)
            if key in d:
                return key
        return _length_key(min(float(k) for k in numeric))

    @property
    def primary_length_mm(self) -> float | None:
        """Выбранная основная длина артикула (#81), или первая по возрастанию.

        Безопасен в async без загрузки relationship: если ``lengths`` не
        загружены — возвращает None (caller фолбэчит на dict-ключи).
        """
        if "lengths" in instance_state(self).unloaded:
            return None
        lengths = self.lengths or []
        if not lengths:
            return None
        primary = [l.length_mm for l in lengths if l.is_primary]
        if primary:
            return min(primary)
        return min(l.length_mm for l in lengths)

    def _value_for_mode(self, entry: dict) -> int | None:
        """Значение per-length записи строго по hanger_mode (#127).

        Отображается и используется значение выбранного режима: auto →
        ``auto``, manual → ``manual``. Приоритета «авто > ручное» больше
        нет; ручное значение никогда не затирается автоматикой.
        """
        if self.hanger_mode == HANGER_MODE_MANUAL:
            manual = entry.get("manual")
            return int(manual) if manual is not None else None
        auto = entry.get("auto")
        return int(auto) if auto is not None else None

    @property
    def quantity_per_hanger(self) -> int | None:
        """Эффективное значение для основной длины по hanger_mode (#127).

        Обратная совместимость для потребителей, которым нужен один скаляр
        (план-импорт, ZIP-импорт, старые тесты). Каноническое per-length
        представление — :attr:`quantity_per_hanger_by_length`. Bare-словарь
        (legacy-скаляр) всегда отдаёт manual — скаляр хранился в manual.
        """
        d = self._hanger_dict()
        if d is None:
            raw = (self.attributes or {}).get("quantity_per_hanger")
            return raw if isinstance(raw, int) else None
        key = self._primary_hanger_length_key()
        if key is None:
            # Bare dict {auto, manual} (legacy-скаляр) — всегда manual.
            manual = d.get("manual")
            return int(manual) if manual is not None else None
        entry = d.get(key)
        if not isinstance(entry, dict):
            return None
        return self._value_for_mode(entry)

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
            primary = self.primary_length_mm
            if primary is None:
                return None
            return {_length_key(primary): _normalize_entry(d)}
        normalized = {
            _length_key(float(k)): _normalize_entry(v)
            for k, v in d.items()
            if isinstance(v, dict)
        }
        return normalized or None

    def quantity_per_hanger_for_length(self, length_mm: float) -> int | None:
        """Значение на подвес для конкретной длины строго по hanger_mode (#127)."""
        d = self._hanger_dict()
        if d is None:
            raw = (self.attributes or {}).get("quantity_per_hanger")
            return raw if isinstance(raw, int) else None
        entry = d.get(_length_key(length_mm))
        if not isinstance(entry, dict):
            # Bare dict без ключа длины (legacy-скаляр) — всегда manual.
            if not _is_numeric_key(next(iter(d), "")):
                manual = d.get("manual")
                return int(manual) if manual is not None else None
            return None
        return self._value_for_mode(entry)

    def main_quantity_per_hanger(self) -> int | None:
        """Скаляр для обратной совместимости: значение для основной длины.

        Основная длина — выбранная пользователем (#81, is_primary), либо
        первая длина из ProductLength по возрастанию. Без обязательного
        обращения к relationship (для уже загруженных lengths). Используется
        потребителями, которым нужен один скаляр (например, план-импорт).
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
    # Состав ГП (#147): нормативные компоненты этого продукта.
    composition: Mapped[list["ProductComposition"]] = relationship(
        "ProductComposition",
        back_populates="product",
        cascade="all, delete-orphan",
        foreign_keys="ProductComposition.product_id",
        order_by="ProductComposition.id",
    )


class ProductLength(Base):
    __tablename__ = "product_lengths"
    __table_args__ = (
        CheckConstraint("length_mm > 0", name="positive"),
        Index(
            "uq_product_lengths_one_primary_per_product",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    length_mm: Mapped[float] = mapped_column(Float, nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

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


class ProductComposition(Base):
    """Состав ГП (#147): нормативная связь «продукт → компонент + количество».

    По образцу BoM (component_id + qty + unit), без факта и остатков.
    Компонент — только сырьё (``type=component``), 1–2 компонента на продукт:
    лимит держит триггер БД (миграция 053), валидация — на products API.
    """

    __tablename__ = "product_compositions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_product_compositions_quantity_positive"),
        UniqueConstraint("product_id", "component_product_id", name="uq_product_compositions_component"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'pcs'"), default="pcs")

    product: Mapped["Product"] = relationship(
        "Product", back_populates="composition", foreign_keys=[product_id]
    )
    component: Mapped["Product"] = relationship("Product", foreign_keys=[component_product_id])
