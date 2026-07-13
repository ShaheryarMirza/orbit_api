from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.shop import SageSyncStatus, Shop, ShopApprovalStatus
from app.models.user import User
from app.schemas.shop import ShopApprovalUpdate, ShopCreate, ShopListResponse, ShopResponse


router = APIRouter(tags=["shops"])


def validate_approval_status_filter(approval_status: str | None) -> str | None:
    if approval_status is None:
        return None

    allowed_statuses = {
        ShopApprovalStatus.PENDING.value,
        ShopApprovalStatus.APPROVED.value,
        ShopApprovalStatus.REJECTED.value,
    }
    if approval_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval_status must be one of: pending, approved, rejected",
        )

    return approval_status


def validate_sage_sync_status_filter(sage_sync_status: str | None) -> str | None:
    if sage_sync_status is None:
        return None

    allowed_statuses = {
        SageSyncStatus.PENDING.value,
        SageSyncStatus.SYNCED.value,
        SageSyncStatus.FAILED.value,
    }
    if sage_sync_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sage_sync_status must be one of: pending, synced, failed",
        )

    return sage_sync_status


@router.post(
    "/shops/register",
    response_model=ShopResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_shop(
    payload: ShopCreate,
    current_user: Annotated[User, Depends(require_roles("shop_owner"))],
    db: Annotated[Session, Depends(get_db)],
) -> Shop:
    existing_shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
    if existing_shop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shop is already registered for this user",
        )

    # Autogenerate account_ref starting with 'OR1'
    import re
    all_refs = db.query(Shop.account_ref).filter(Shop.account_ref.like("OR1%")).all()
    max_num = 1000
    for ref_tuple in all_refs:
        ref = ref_tuple[0]
        if ref:
            match = re.match(r"^OR1(\d+)$", ref)
            if match:
                val = int(match.group(1))
                if val > max_num:
                    max_num = val
    next_ref = f"OR1{max_num + 1}"

    shop = Shop(
        user_id=current_user.id,
        company_name=payload.company_name.strip(),
        phone_number=payload.phone_number.strip(),
        address=payload.address.strip(),
        address_line_2=(
            payload.address_line_2.strip()
            if payload.address_line_2
            else None
        ),
        postcode=payload.postcode.strip(),
        city=payload.city.strip(),
        country=payload.country.strip(),
        company_registration_number=(
            payload.company_registration_number.strip()
            if payload.company_registration_number
            else None
        ),
        fax=(
            payload.fax.strip()
            if payload.fax
            else None
        ),
        website=(
            payload.website.strip()
            if payload.website
            else None
        ),
        account_ref=next_ref,
    )

    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


@router.get("/shops/me", response_model=ShopResponse)
def get_my_shop(
    current_user: Annotated[User, Depends(require_roles("shop_owner"))],
    db: Annotated[Session, Depends(get_db)],
) -> Shop:
    shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop registration not found",
        )
    return shop


@router.get("/admin/shops", response_model=ShopListResponse)
def get_all_shops(
    current_user: Annotated[User, Depends(require_roles("admin", "salesperson"))],
    db: Annotated[Session, Depends(get_db)],
    approval_status: str | None = None,
    sage_sync_status: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ShopListResponse:
    approval_status_filter = validate_approval_status_filter(approval_status)
    sage_sync_status_filter = validate_sage_sync_status_filter(sage_sync_status)
    query = db.query(Shop)

    if approval_status_filter is not None:
        query = query.filter(Shop.approval_status == approval_status_filter)
    if sage_sync_status_filter is not None:
        query = query.filter(Shop.sage_sync_status == sage_sync_status_filter)
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Shop.company_name.ilike(search_pattern),
                Shop.account_ref.ilike(search_pattern),
                Shop.phone_number.ilike(search_pattern),
                Shop.postcode.ilike(search_pattern),
                Shop.city.ilike(search_pattern),
                Shop.company_registration_number.ilike(search_pattern),
            )
        )

    total = query.count()
    pages = (total + page_size - 1) // page_size if total else 0
    items = (
        query.order_by(Shop.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return ShopListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.patch("/admin/shops/{shop_id}/approval", response_model=ShopResponse)
def update_shop_approval(
    shop_id: int,
    payload: ShopApprovalUpdate,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> Shop:
    if payload.approval_status == ShopApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval status must be approved or rejected",
        )

    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found",
        )

    shop.approval_status = payload.approval_status.value
    if payload.account_ref is not None:
        shop.account_ref = payload.account_ref.strip() or None
    db.commit()
    db.refresh(shop)
    return shop
