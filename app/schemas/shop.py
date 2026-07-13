from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.shop import ShopApprovalStatus


class ShopCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    phone_number: str = Field(min_length=1, max_length=50)
    address: str = Field(min_length=1, max_length=500)
    address_line_2: str | None = Field(default=None, max_length=255)
    postcode: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=1, max_length=100)
    company_registration_number: str | None = Field(default=None, max_length=50)
    fax: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=255)
    account_ref: str | None = Field(default=None, max_length=100)


class ShopResponse(BaseModel):
    id: int
    user_id: int
    company_name: str
    phone_number: str
    address: str
    address_line_2: str | None
    postcode: str
    city: str
    country: str
    company_registration_number: str | None
    fax: str | None
    website: str | None
    approval_status: str
    sage_customer_id: str | None
    account_ref: str
    sage_sync_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShopApprovalUpdate(BaseModel):
    approval_status: ShopApprovalStatus
    account_ref: str | None = Field(default=None, max_length=100)


class ShopListResponse(BaseModel):
    items: list[ShopResponse]
    total: int
    page: int
    page_size: int
    pages: int
