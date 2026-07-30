from datetime import datetime

from pydantic import BaseModel


class DimensionTypeIn(BaseModel):
    code: str
    name: str
    unit: str
    value_type: str = "number"


class DimensionTypePatch(BaseModel):
    code: str | None = None
    name: str | None = None
    unit: str | None = None
    value_type: str | None = None


class DimensionTypeOut(BaseModel):
    id: int
    code: str
    name: str
    unit: str
    value_type: str
    created_at: datetime


class ProductDimensionIn(BaseModel):
    dimension_type_id: int
    is_required: bool = False
    default_value: float | None = None


class ProductDimensionPatch(BaseModel):
    is_required: bool | None = None
    default_value: float | None = None


class ProductDimensionOut(BaseModel):
    id: int
    product_id: int
    dimension_type_id: int
    is_required: bool
    default_value: float | None
    dimension_type: DimensionTypeOut
