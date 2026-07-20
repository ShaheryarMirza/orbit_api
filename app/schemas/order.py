from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.order import DiscountType


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    vat_rate: float | None = Field(default=None, ge=0.0)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)
    customer_reference: str | None = Field(default=None, max_length=255)


class AssistedOrderCreate(BaseModel):
    shop_id: int
    items: list[OrderItemCreate] = Field(min_length=1)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(default=None, ge=0)
    customer_reference: str | None = Field(default=None, max_length=255)
    internal_notes: str | None = Field(default=None, max_length=1000)


class SageSyncedRequest(BaseModel):
    sage_sales_order_id: str = Field(min_length=1, max_length=100)

    @field_validator("sage_sales_order_id")
    @classmethod
    def validate_sage_sales_order_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("sage_sales_order_id must not be empty")
        return cleaned


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    vat_rate: float
    vat_amount: float

    model_config = ConfigDict(from_attributes=True)


class SalespersonResponse(BaseModel):
    id: int
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class ShopMiniResponse(BaseModel):
    id: int
    company_name: str
    phone_number: str
    address: str
    postcode: str
    city: str
    account_ref: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    order_number: str | None
    shop_id: int
    created_by_user_id: int
    created_by_role: str
    salesperson_id: int | None
    customer_reference: str | None
    internal_notes: str | None
    subtotal: Decimal
    discount_type: str | None
    discount_value: Decimal | None
    discount_amount: Decimal
    final_total: Decimal
    total_vat: float
    status: str
    sage_sales_order_id: str | None
    sage_sync_status: str
    account_ref: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]
    salesperson: SalespersonResponse | None = None
    shop: ShopMiniResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    pages: int


class OrderSummaryResponse(BaseModel):
    total_orders: int
    placed_orders: int
    cancelled_orders: int
    subtotal_total: Decimal
    discount_total: Decimal
    final_total: Decimal
    pending_sage_sync: int


class SalesOrderDetailOrderResponse(BaseModel):
    id: int
    order_number: str | None
    status: str
    created_at: datetime
    created_by_role: str
    customer_reference: str | None
    subtotal: Decimal
    discount_type: str | None
    discount_value: Decimal | None
    discount_amount: Decimal
    final_total: Decimal
    total_vat: float
    sage_sync_status: str
    salesperson_id: int | None = None
    sage_order_number: str | None = None
    sync_notes: str | None = None


class SalesOrderDetailShopResponse(BaseModel):
    id: int
    company_name: str
    phone_number: str
    address: str
    postcode: str
    city: str


class SalesOrderDetailItemResponse(BaseModel):
    product_code: str
    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    vat_rate: float
    vat_amount: float


class SalesOrderDetailResponse(BaseModel):
    order: SalesOrderDetailOrderResponse
    shop: SalesOrderDetailShopResponse
    items: list[SalesOrderDetailItemResponse]
