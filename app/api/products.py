import csv
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.category import Category, SubCategory
from app.models.product import Product
from app.models.user import User
from app.utils.file_storage import save_upload_file
from app.schemas.product import (
    ProductCreate,
    ProductCsvImportError,
    ProductCsvImportResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)


router = APIRouter(prefix="/products", tags=["products"])
read_roles = require_roles("admin", "salesperson", "shop_owner")
inventory_roles = require_roles("admin", "salesperson")
admin_role = require_roles("admin")


def clean_required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} is required",
        )
    return cleaned


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


def get_active_product_or_404(product_id: int, db: Session) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.is_active.is_(True))
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    description="Admin-only endpoint for creating products.",
)
def create_product(
    payload: ProductCreate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    if payload.category_id is not None:
        category = db.query(Category).filter(Category.id == payload.category_id, Category.is_active.is_(True)).first()
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    if payload.subcategory_id is not None:
        get_active_subcategory_or_404(payload.subcategory_id, db)
    product = Product(
        category_id=payload.category_id,
        subcategory_id=payload.subcategory_id,
        product_code=clean_required_text(payload.product_code, "Product code"),
        product_name=clean_required_text(payload.product_name, "Product name"),
        description=payload.description.strip() if payload.description else None,
        price=payload.price,
        quantity=payload.quantity,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product code already exists",
        ) from exc
    db.refresh(product)
    return product


@router.get(
    "",
    response_model=ProductListResponse,
    summary="List products",
    description="Available to admin, salesperson, and shop owner users.",
)
def list_products(
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    category_slug: str | None = None,
    subcategory_slug: str | None = None,
    is_active: bool | None = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100000),
) -> ProductListResponse:
    query = db.query(Product)

    if category_id is not None:
        query = query.filter(Product.category_id == category_id)
    if category_slug:
        query = query.join(Product.category).filter(Category.slug == category_slug)
    if subcategory_id is not None:
        query = query.filter(Product.subcategory_id == subcategory_id)
    if subcategory_slug:
        query = query.join(Product.subcategory).filter(SubCategory.slug == subcategory_slug)
    if is_active is not None:
        query = query.filter(Product.is_active.is_(is_active))
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Product.product_code.ilike(search_pattern),
                Product.product_name.ilike(search_pattern),
                Product.description.ilike(search_pattern),
            )
        )

    total = query.count()
    pages = (total + page_size - 1) // page_size if total else 0
    items = (
        query.order_by(Product.product_name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return ProductListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/low-stock",
    response_model=list[ProductResponse],
    summary="List low-stock products",
    description=(
        "Available to admin and salesperson users. Returns active products "
        "whose quantity is less than or equal to the threshold."
    ),
)
def list_low_stock_products(
    current_user: Annotated[User, Depends(inventory_roles)],
    db: Annotated[Session, Depends(get_db)],
    threshold: int = Query(default=10, ge=0),
) -> list[Product]:
    return (
        db.query(Product)
        .filter(
            Product.is_active.is_(True),
            Product.quantity <= threshold,
        )
        .order_by(Product.quantity.asc(), Product.product_name.asc())
        .all()
    )


@router.post(
    "/import-csv",
    response_model=ProductCsvImportResponse,
    summary="Import products from CSV",
    description=(
        "Admin-only CSV import. Valid rows are created; duplicate product codes "
        "and invalid rows are skipped without updating existing products."
    ),
)
async def import_products_csv(
    file: Annotated[UploadFile, File(description="CSV file containing products")],
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> ProductCsvImportResponse:
    filename = file.filename or ""
    allowed_content_types = {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
    }
    if not filename.lower().endswith(".csv") or (
        file.content_type and file.content_type not in allowed_content_types
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are accepted",
        )

    try:
        content = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file must use UTF-8 encoding",
        ) from exc

    reader = csv.DictReader(StringIO(content))
    required_columns = {
        "product_code",
        "product_name",
        "price",
        "quantity",
        "subcategory_id",
    }
    fieldnames = {name.strip() for name in reader.fieldnames or [] if name}
    missing_columns = sorted(required_columns - fieldnames)
    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required CSV columns: {', '.join(missing_columns)}",
        )

    existing_codes = {
        code for (code,) in db.query(Product.product_code).all()
    }
    valid_subcategory_ids = {
        subcategory_id for (subcategory_id,) in db.query(SubCategory.id).all()
    }
    errors: list[ProductCsvImportError] = []
    created = 0
    skipped = 0

    for row_number, row in enumerate(reader, start=2):
        normalized_row = {
            (key.strip() if key else ""): (value.strip() if value else "")
            for key, value in row.items()
        }
        product_code = normalized_row.get("product_code", "")
        product_name = normalized_row.get("product_name", "")

        try:
            if not product_code:
                raise ValueError("product_code is required")
            if len(product_code) > 100:
                raise ValueError("product_code must be 100 characters or fewer")
            if product_code in existing_codes:
                raise ValueError("product_code already exists")
            if not product_name:
                raise ValueError("product_name is required")
            if len(product_name) > 255:
                raise ValueError("product_name must be 255 characters or fewer")

            try:
                price = Decimal(normalized_row.get("price", ""))
            except InvalidOperation as exc:
                raise ValueError("price must be a valid number") from exc
            if not price.is_finite() or price < 0:
                raise ValueError("price must be greater than or equal to 0")

            try:
                quantity = int(normalized_row.get("quantity", ""))
            except ValueError as exc:
                raise ValueError("quantity must be a valid integer") from exc
            if quantity < 0:
                raise ValueError("quantity must be greater than or equal to 0")

            try:
                subcategory_id = int(normalized_row.get("subcategory_id", ""))
            except ValueError as exc:
                raise ValueError("subcategory_id must be a valid integer") from exc
            if subcategory_id not in valid_subcategory_ids:
                raise ValueError("subcategory_id does not exist")

            product = Product(
                product_code=product_code,
                product_name=product_name,
                price=price,
                quantity=quantity,
                subcategory_id=subcategory_id,
            )
            try:
                with db.begin_nested():
                    db.add(product)
                    db.flush()
            except IntegrityError as exc:
                raise ValueError("product_code already exists") from exc

            existing_codes.add(product_code)
            created += 1
        except ValueError as exc:
            skipped += 1
            errors.append(
                ProductCsvImportError(row=row_number, error=str(exc))
            )

    db.commit()
    return ProductCsvImportResponse(
        created=created,
        skipped=skipped,
        errors=errors,
    )


@router.get(
    "/export-csv",
    summary="Export products to CSV",
    description=(
        "Available to admin and salesperson users. Exports products using "
        "the same search and filtering options as the product list."
    ),
)
def export_products_csv(
    current_user: Annotated[User, Depends(inventory_roles)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    is_active: bool | None = True,
) -> StreamingResponse:
    query = (
        db.query(Product, SubCategory, Category)
        .join(SubCategory, Product.subcategory_id == SubCategory.id)
        .join(Category, SubCategory.category_id == Category.id)
    )

    if category_id is not None:
        query = query.filter(Category.id == category_id)
    if subcategory_id is not None:
        query = query.filter(Product.subcategory_id == subcategory_id)
    if is_active is not None:
        query = query.filter(Product.is_active.is_(is_active))
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Product.product_code.ilike(search_pattern),
                Product.product_name.ilike(search_pattern),
            )
        )

    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "product_code",
            "product_name",
            "price",
            "quantity",
            "subcategory_id",
            "subcategory_name",
            "category_id",
            "category_name",
            "is_active",
        ]
    )

    for product, subcategory, category in query.order_by(
        Product.product_name.asc()
    ).all():
        writer.writerow(
            [
                product.product_code,
                product.product_name,
                f"{product.price:.2f}",
                product.quantity,
                subcategory.id,
                subcategory.name,
                category.id,
                category.name,
                str(product.is_active).lower(),
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="products_export.csv"',
        },
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product",
    description="Available to admin, salesperson, and shop owner users.",
)
def get_product(
    product_id: int,
    current_user: Annotated[User, Depends(read_roles)],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    return get_active_product_or_404(product_id, db)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product",
    description="Admin-only endpoint for editing products.",
)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    product = get_active_product_or_404(product_id, db)

    if "category_id" in payload.model_fields_set:
        if payload.category_id is not None:
            category = db.query(Category).filter(Category.id == payload.category_id, Category.is_active.is_(True)).first()
            if not category:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        product.category_id = payload.category_id

    if "subcategory_id" in payload.model_fields_set:
        if payload.subcategory_id is not None:
            get_active_subcategory_or_404(payload.subcategory_id, db)
        product.subcategory_id = payload.subcategory_id
    if payload.product_code is not None:
        product.product_code = clean_required_text(payload.product_code, "Product code")
    if payload.product_name is not None:
        product.product_name = clean_required_text(payload.product_name, "Product name")
    if "description" in payload.model_fields_set:
        product.description = payload.description.strip() if payload.description else None
    if payload.price is not None:
        product.price = payload.price
    if payload.quantity is not None:
        product.quantity = payload.quantity
    if payload.is_active is not None:
        product.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product code already exists",
        ) from exc
    db.refresh(product)
    return product


@router.delete(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Soft delete a product",
    description="Admin-only endpoint. Sets is_active to false.",
)
def delete_product(
    product_id: int,
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    product = get_active_product_or_404(product_id, db)
    product.is_active = False
    db.commit()
    db.refresh(product)
    return product


@router.post(
    "/{product_id}/image",
    response_model=ProductResponse,
    summary="Upload product image",
    description="Admin-only endpoint for uploading a product image.",
)
def upload_product_image(
    product_id: int,
    file: Annotated[UploadFile, File(description="Product image file")],
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> Product:
    product = get_active_product_or_404(product_id, db)
    file_url = save_upload_file(file, "products")
    product.image_url = file_url
    db.commit()
    db.refresh(product)
    return product


def find_column(df: pd.DataFrame, possible_names: list[str]) -> str | None:
    for col in df.columns:
        if str(col).strip().lower() in possible_names:
            return col
    return None


@router.post(
    "/import",
    response_model=ProductCsvImportResponse,
    summary="Bulk import products from CSV/Excel",
    description="Admin-only endpoint for importing products from Excel or CSV.",
)
async def import_products(
    file: Annotated[UploadFile, File(description="Excel or CSV file containing products")],
    current_user: Annotated[User, Depends(admin_role)],
    db: Annotated[Session, Depends(get_db)],
) -> ProductCsvImportResponse:
    import io
    import re
    import pandas as pd
    
    filename = file.filename or ""
    is_csv = filename.lower().endswith(".csv")
    is_excel = filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls")

    if not (is_csv or is_excel):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only Excel (.xlsx, .xls) and CSV (.csv) files are supported."
        )

    try:
        contents = await file.read()
        if is_csv:
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse spreadsheet file: {str(exc)}"
        )

    df.columns = [str(c).strip() for c in df.columns]

    col_cat = find_column(df, ["category", "categories"])
    col_name = find_column(df, ["name", "product name", "product_name"])
    col_desc = find_column(df, ["description", "product description", "product_description"])
    col_price = find_column(df, ["price", "unit price", "unit_price", "price (ex. vat)", "price"])
    col_image = find_column(df, ["image", "picture url", "picture_url", "image_url", "image url", "pictureurl"])

    if not col_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet must contain a 'Name' or 'Product Name' column."
        )
    if not col_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet must contain a 'Price' column."
        )

    errors = []
    created = 0
    skipped = 0

    for idx, row in df.iterrows():
        row_number = idx + 2
        try:
            name_val = str(row[col_name]).strip() if pd.notna(row[col_name]) else ""
            if not name_val:
                errors.append(ProductCsvImportError(row=row_number, error="Product name is required."))
                continue

            # Try matching SKU at the beginning: e.g. "00035-03 Ulker Baby Biscuit..."
            match = re.match(r"^([a-zA-Z0-9\-]+)\s+(.*)$", name_val)
            if match:
                product_code = match.group(1).strip()
                product_name = match.group(2).strip()
                product_name = re.sub(r"^[\-\:\s]+", "", product_name)
            else:
                product_code = name_val
                product_name = name_val

            if len(product_code) > 100:
                errors.append(ProductCsvImportError(row=row_number, error="Product code must be 100 characters or fewer."))
                continue
            if len(product_name) > 255:
                errors.append(ProductCsvImportError(row=row_number, error="Product name must be 255 characters or fewer."))
                continue

            # Parse category
            cat_val = str(row[col_cat]).strip() if col_cat and pd.notna(row[col_cat]) else ""
            category_id = None
            if cat_val:
                category = db.query(Category).filter(Category.name.ilike(cat_val)).first()
                if not category:
                    category = Category(
                        name=cat_val,
                        slug=cat_val.lower().replace("&", "and").replace(" ", "-").replace("--", "-")
                    )
                    db.add(category)
                    db.flush()
                category_id = category.id

            # Parse price
            price_val = Decimal("0.00")
            if col_price and pd.notna(row[col_price]):
                price_str = str(row[col_price]).strip().replace("£", "").replace(",", "")
                try:
                    price_val = Decimal(price_str)
                except InvalidOperation:
                    errors.append(ProductCsvImportError(row=row_number, error="Price must be a valid number."))
                    continue
            if price_val < 0:
                errors.append(ProductCsvImportError(row=row_number, error="Price must be greater than or equal to 0."))
                continue

            # Parse optional fields
            desc_val = str(row[col_desc]).strip() if col_desc and pd.notna(row[col_desc]) else None
            image_val = str(row[col_image]).strip() if col_image and pd.notna(row[col_image]) else None

            # Add or update
            product = db.query(Product).filter(Product.product_code == product_code).first()
            if product:
                product.product_name = product_name
                product.description = desc_val
                product.price = price_val
                if category_id is not None:
                    product.category_id = category_id
                if image_val is not None:
                    product.image_url = image_val
                db.flush()
                created += 1
            else:
                product = Product(
                    product_code=product_code,
                    product_name=product_name,
                    description=desc_val,
                    price=price_val,
                    category_id=category_id,
                    image_url=image_val,
                    is_active=True,
                    quantity=0
                )
                db.add(product)
                db.flush()
                created += 1

        except Exception as exc:
            errors.append(ProductCsvImportError(row=row_number, error=str(exc)))
            continue

    db.commit()
    return ProductCsvImportResponse(
        created=created,
        skipped=skipped,
        errors=errors
    )
