from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserRole


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    role: UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    must_change_password: bool
    is_approved: bool

    model_config = ConfigDict(from_attributes=True)


class RegisterShopRequest(BaseModel):
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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=255)
    shop: RegisterShopRequest


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)
    confirm_new_password: str = Field(min_length=1)
