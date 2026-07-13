from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Category name")
    slug: str = Field(min_length=1, max_length=255, description="Category slug")
    description: str | None = Field(default=None, max_length=1000)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str | None
    description: str | None
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubCategoryCreate(BaseModel):
    category_id: int = Field(description="Parent category ID")
    name: str = Field(min_length=1, max_length=255, description="Subcategory name")
    slug: str = Field(min_length=1, max_length=255, description="Subcategory slug")
    description: str | None = Field(default=None, max_length=1000)


class SubCategoryUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class SubCategoryResponse(BaseModel):
    id: int
    category_id: int
    name: str
    slug: str | None
    description: str | None
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryWithSubcategoriesResponse(CategoryResponse):
    subcategories: list[SubCategoryResponse] = []
