from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.category import Category, SubCategory
from app.models.user import User
from app.utils.file_storage import save_upload_file
from app.schemas.category import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    CategoryWithSubcategoriesResponse,
    SubCategoryCreate,
    SubCategoryResponse,
    SubCategoryUpdate,
)


router = APIRouter(prefix="/api", tags=["catalog"])
read_roles = require_roles("admin", "salesperson", "shop_owner")
admin_role = require_roles("admin")


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def clean_required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} is required",
        )
    return cleaned


def get_active_category_or_404(category_id: int, db: Session) -> Category:
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.is_active.is_(True))
        .first()
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    return category


def get_active_subcategory_or_404(subcategory_id: int, db: Session) -> SubCategory:
    subcategory = (
        db.query(SubCategory)
        .filter(SubCategory.id == subcategory_id, SubCategory.is_active.is_(True))
        .first()
    )
    if not subcategory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subcategory not found",
        )
    return subcategory


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    description="Admin-only endpoint for creating product categories.",
)
def create_category(
    payload: CategoryCreate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = Category(
        name=clean_required_text(payload.name, "Category name"),
        slug=clean_required_text(payload.slug, "Category slug"),
        description=clean_optional_text(payload.description),
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name or slug already exists",
        ) from exc
    db.refresh(category)
    return category


@router.get(
    "/categories",
    response_model=list[CategoryWithSubcategoriesResponse],
    summary="List categories",
    description="Available to admin, salesperson, and shop owner users.",
)
def list_categories(
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Category]:
    categories = (
        db.query(Category)
        .filter(Category.is_active.is_(True))
        .options(joinedload(Category.subcategories))
        .order_by(Category.name.asc())
        .all()
    )
    for cat in categories:
        cat.subcategories = [sub for sub in cat.subcategories if sub.is_active]
    return categories


@router.get(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    summary="Get a category",
    description="Available to admin, salesperson, and shop owner users.",
)
def get_category(
    category_id: int,
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    return get_active_category_or_404(category_id, db)


@router.put(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    summary="Update a category (PUT)",
    description="Admin-only endpoint for editing product categories.",
)
def put_category(
    category_id: int,
    payload: CategoryUpdate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = get_active_category_or_404(category_id, db)

    if payload.name is not None:
        category.name = clean_required_text(payload.name, "Category name")
    if payload.slug is not None:
        category.slug = clean_required_text(payload.slug, "Category slug")
    if "description" in payload.model_fields_set:
        category.description = clean_optional_text(payload.description)
    if payload.is_active is not None:
        category.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name or slug already exists",
        ) from exc
    db.refresh(category)
    return category


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    summary="Update a category (PATCH)",
    description="Admin-only endpoint for editing product categories.",
)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = get_active_category_or_404(category_id, db)

    if payload.name is not None:
        category.name = clean_required_text(payload.name, "Category name")
    if payload.slug is not None:
        category.slug = clean_required_text(payload.slug, "Category slug")
    if "description" in payload.model_fields_set:
        category.description = clean_optional_text(payload.description)
    if payload.is_active is not None:
        category.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name or slug already exists",
        ) from exc
    db.refresh(category)
    return category


@router.delete(
    "/categories/{category_id}",
    response_model=CategoryResponse,
    summary="Soft delete a category",
    description="Admin-only endpoint. Sets is_active to false.",
)
def delete_category(
    category_id: int,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = get_active_category_or_404(category_id, db)
    category.is_active = False
    db.commit()
    db.refresh(category)
    return category


@router.post(
    "/subcategories",
    response_model=SubCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subcategory",
    description="Admin-only endpoint for creating product subcategories.",
)
def create_subcategory(
    payload: SubCategoryCreate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    get_active_category_or_404(payload.category_id, db)
    subcategory = SubCategory(
        category_id=payload.category_id,
        name=clean_required_text(payload.name, "Subcategory name"),
        slug=clean_required_text(payload.slug, "Subcategory slug"),
        description=clean_optional_text(payload.description),
    )
    db.add(subcategory)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subcategory slug already exists for this category",
        ) from exc
    db.refresh(subcategory)
    return subcategory


@router.get(
    "/subcategories",
    response_model=list[SubCategoryResponse],
    summary="List subcategories",
    description="Available to admin, salesperson, and shop owner users.",
)
def list_subcategories(
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SubCategory]:
    return (
        db.query(SubCategory)
        .filter(SubCategory.is_active.is_(True))
        .order_by(SubCategory.name.asc())
        .all()
    )


@router.get(
    "/subcategories/{subcategory_id}",
    response_model=SubCategoryResponse,
    summary="Get a subcategory",
    description="Available to admin, salesperson, and shop owner users.",
)
def get_subcategory(
    subcategory_id: int,
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    return get_active_subcategory_or_404(subcategory_id, db)


@router.put(
    "/subcategories/{subcategory_id}",
    response_model=SubCategoryResponse,
    summary="Update a subcategory (PUT)",
    description="Admin-only endpoint for editing product subcategories.",
)
def put_subcategory(
    subcategory_id: int,
    payload: SubCategoryUpdate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    subcategory = get_active_subcategory_or_404(subcategory_id, db)

    if payload.category_id is not None:
        get_active_category_or_404(payload.category_id, db)
        subcategory.category_id = payload.category_id
    if payload.name is not None:
        subcategory.name = clean_required_text(payload.name, "Subcategory name")
    if payload.slug is not None:
        subcategory.slug = clean_required_text(payload.slug, "Subcategory slug")
    if "description" in payload.model_fields_set:
        subcategory.description = clean_optional_text(payload.description)
    if payload.is_active is not None:
        subcategory.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subcategory name or slug already exists",
        ) from exc
    db.refresh(subcategory)
    return subcategory


@router.patch(
    "/subcategories/{subcategory_id}",
    response_model=SubCategoryResponse,
    summary="Update a subcategory (PATCH)",
    description="Admin-only endpoint for editing product subcategories.",
)
def update_subcategory(
    subcategory_id: int,
    payload: SubCategoryUpdate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    subcategory = get_active_subcategory_or_404(subcategory_id, db)

    if payload.category_id is not None:
        get_active_category_or_404(payload.category_id, db)
        subcategory.category_id = payload.category_id
    if payload.name is not None:
        subcategory.name = clean_required_text(payload.name, "Subcategory name")
    if payload.slug is not None:
        subcategory.slug = clean_required_text(payload.slug, "Subcategory slug")
    if "description" in payload.model_fields_set:
        subcategory.description = clean_optional_text(payload.description)
    if payload.is_active is not None:
        subcategory.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subcategory name or slug already exists",
        ) from exc
    db.refresh(subcategory)
    return subcategory


@router.delete(
    "/subcategories/{subcategory_id}",
    response_model=SubCategoryResponse,
    summary="Soft delete a subcategory",
    description="Admin-only endpoint. Sets is_active to false.",
)
def delete_subcategory(
    subcategory_id: int,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    subcategory = get_active_subcategory_or_404(subcategory_id, db)
    subcategory.is_active = False
    db.commit()
    db.refresh(subcategory)
    return subcategory


@router.post(
    "/categories/{category_id}/image",
    response_model=CategoryResponse,
    summary="Upload category image",
    description="Admin-only endpoint for uploading a category image.",
)
def upload_category_image(
    category_id: int,
    file: Annotated[UploadFile, File(description="Category image file")],
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = get_active_category_or_404(category_id, db)
    file_url = save_upload_file(file, "categories")
    category.image_url = file_url
    db.commit()
    db.refresh(category)
    return category


@router.post(
    "/subcategories/{subcategory_id}/image",
    response_model=SubCategoryResponse,
    summary="Upload subcategory image",
    description="Admin-only endpoint for uploading a subcategory image.",
)
def upload_subcategory_image(
    subcategory_id: int,
    file: Annotated[UploadFile, File(description="Subcategory image file")],
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> SubCategory:
    subcategory = get_active_subcategory_or_404(subcategory_id, db)
    file_url = save_upload_file(file, "subcategories")
    subcategory.image_url = file_url
    db.commit()
    db.refresh(subcategory)
    return subcategory
