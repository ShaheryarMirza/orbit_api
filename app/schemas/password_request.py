from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class PasswordResetRequestCreate(BaseModel):
    account_ref: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=1, max_length=50)


class PasswordResetRequestResponse(BaseModel):
    id: int
    account_ref: str
    company_name: str
    email: str
    phone_number: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PasswordResetResolveRequest(BaseModel):
    new_password: str | None = Field(default=None, min_length=4, max_length=255)
