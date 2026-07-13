from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    category_id: int | None = Field(default=None, description="Parent category ID")
    subcategory_id: int | None = Field(default=None, description="Parent subcategory ID")
    product_code: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(ge=0, decimal_places=2)
    quantity: int = Field(default=0, ge=0)


class ProductUpdate(BaseModel):
    category_id: int | None = None
    subcategory_id: int | None = None
    product_code: str | None = Field(default=None, min_length=1, max_length=100)
    product_name: str | None = Field(default=None, min_length=1, max_length=255)
    price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    quantity: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductResponse(BaseModel):
    id: int
    category_id: int | None = None
    subcategory_id: int | None = None
    product_code: str
    product_name: str
    image_url: str | None = None
    price: Decimal
    quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ProductCsvImportError(BaseModel):
    row: int
    error: str


class ProductCsvImportResponse(BaseModel):
    created: int
    skipped: int
    errors: list[ProductCsvImportError]
