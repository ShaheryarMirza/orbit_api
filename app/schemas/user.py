from pydantic import BaseModel, Field

class SalespersonCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=255)

class AdminCreate(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=255)

class SalespersonUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=4)
