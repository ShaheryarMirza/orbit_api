
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.order import Order, OrderItem
from app.models.shop import SageSyncStatus, Shop, ShopApprovalStatus
from app.models.user import User
from app.schemas.shop import ShopApprovalUpdate, ShopCreate, ShopListResponse, ShopResponse, ShopProfileUpdate, ShopUpdate


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
    current_user: User = Depends(require_roles("shop_owner")),
    db: Session = Depends(get_db),
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

    contact_name_val = payload.contact_name.strip() if payload.contact_name else current_user.name

    shop = Shop(
        user_id=current_user.id,
        company_name=payload.company_name.strip(),
        contact_name=contact_name_val,
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
        needs_sage_sync=True,
        sage_sync_status=SageSyncStatus.PENDING.value,
    )

    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


@router.get("/shops/me", response_model=ShopResponse)
def get_my_shop(
    current_user: User = Depends(require_roles("shop_owner")),
    db: Session = Depends(get_db),
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
    current_user: User = Depends(require_roles("admin", "salesperson")),
    db: Session = Depends(get_db),
    approval_status: str | None = None,
    sage_sync_status: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10000, ge=1, le=100000),
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
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
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
    if payload.approval_status == ShopApprovalStatus.APPROVED:
        shop.is_approved = True
        shop.needs_sage_sync = True
        shop.sage_sync_status = SageSyncStatus.PENDING.value
    elif payload.approval_status == ShopApprovalStatus.REJECTED:
        shop.is_approved = False

    if payload.account_ref is not None:
        shop.account_ref = payload.account_ref.strip() or None
    db.commit()
    db.refresh(shop)
    return shop


@router.patch("/shops/profile", response_model=ShopResponse)
@router.put("/shops/profile", response_model=ShopResponse)
def update_shop_profile(
    payload: ShopProfileUpdate,
    current_user: User = Depends(require_roles("shop_owner")),
    db: Session = Depends(get_db),
) -> Shop:
    shop = db.query(Shop).filter(Shop.user_id == current_user.id).first()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop registration not found",
        )

    # Email uniqueness check if changing email
    email = payload.email.strip().lower()
    if email != current_user.email:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already in use by another account",
            )
        current_user.email = email

    # Update user name too
    current_user.name = payload.contact_name.strip()

    # Update shop properties
    shop.company_name = payload.company_name.strip()
    shop.contact_name = payload.contact_name.strip()
    shop.address = payload.address.strip()
    shop.address_line_2 = payload.address_line_2.strip() if payload.address_line_2 else None
    shop.postcode = payload.postcode.strip()
    shop.city = payload.city.strip()
    shop.country = payload.country.strip()
    shop.phone_number = payload.phone_number.strip()
    shop.telephone_2 = payload.telephone_2.strip() if payload.telephone_2 else None
    shop.telephone_3 = payload.telephone_3.strip() if payload.telephone_3 else None

    # Track Sage Sync
    shop.needs_sage_sync = True
    shop.sage_sync_status = SageSyncStatus.PENDING.value

    db.commit()
    db.refresh(shop)
    return shop


@router.patch("/admin/shops/{shop_id}", response_model=ShopResponse)
@router.put("/admin/shops/{shop_id}", response_model=ShopResponse)
@router.patch("/api/admin/shops/{shop_id}", response_model=ShopResponse)
@router.put("/api/admin/shops/{shop_id}", response_model=ShopResponse)
def update_shop_by_admin(
    shop_id: int,
    payload: ShopUpdate,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found",
        )

    if payload.email and shop.user:
        email = payload.email.strip().lower()
        if email != shop.user.email:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email is already in use by another account",
                )
            shop.user.email = email

    if payload.company_name is not None:
        shop.company_name = payload.company_name.strip()
    if payload.contact_name is not None:
        shop.contact_name = payload.contact_name.strip()
        if shop.user:
            shop.user.name = payload.contact_name.strip()
    if payload.phone_number is not None:
        shop.phone_number = payload.phone_number.strip()
    if payload.telephone_2 is not None:
        shop.telephone_2 = payload.telephone_2.strip() if payload.telephone_2 else None
    if payload.telephone_3 is not None:
        shop.telephone_3 = payload.telephone_3.strip() if payload.telephone_3 else None
    if payload.address is not None:
        shop.address = payload.address.strip()
    if payload.address_line_2 is not None:
        shop.address_line_2 = payload.address_line_2.strip() if payload.address_line_2 else None
    if payload.postcode is not None:
        shop.postcode = payload.postcode.strip()
    if payload.city is not None:
        shop.city = payload.city.strip()
    if payload.country is not None:
        shop.country = payload.country.strip()
    if payload.company_registration_number is not None:
        shop.company_registration_number = payload.company_registration_number.strip() if payload.company_registration_number else None
    if payload.fax is not None:
        shop.fax = payload.fax.strip() if payload.fax else None
    if payload.website is not None:
        shop.website = payload.website.strip() if payload.website else None
    if payload.account_ref is not None:
        shop.account_ref = payload.account_ref.strip()

    shop.needs_sage_sync = True
    shop.sage_sync_status = SageSyncStatus.PENDING.value

    db.commit()
    db.refresh(shop)
    return shop


@router.get("/api/admin/shops/pending", response_model=list[ShopResponse])
def get_pending_shops(
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> list[Shop]:
    return (
        db.query(Shop)
        .filter(Shop.approval_status == ShopApprovalStatus.PENDING.value)
        .all()
    )


@router.patch("/api/admin/shops/{shop_id}/approve", response_model=ShopResponse)
def approve_shop_direct(
    shop_id: int,
    current_user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop registration not found",
        )
    shop.approval_status = ShopApprovalStatus.APPROVED.value
    shop.is_approved = True
    shop.needs_sage_sync = True
    shop.sage_sync_status = SageSyncStatus.PENDING.value
    db.commit()
    db.refresh(shop)
    return shop


@router.delete(
    "/admin/shops/{shop_id}",
    summary="Delete an unsynced shop or pending approval request",
    description="Root Admin only. Deletes a shop or pending registration request if it has not been synced to Sage 50.",
)
@router.delete(
    "/shops/{shop_id}",
    summary="Delete an unsynced shop",
    description="Root Admin only. Deletes a shop if it has not been synced to Sage 50.",
)
@router.delete(
    "/api/admin/shops/pending/{shop_id}",
    summary="Delete a pending approval request",
    description="Root Admin only. Deletes a pending registration request if it has not been synced to Sage 50.",
)
@router.delete(
    "/admin/shops/pending/{shop_id}",
    summary="Delete a pending approval request",
    description="Root Admin only. Deletes a pending registration request if it has not been synced to Sage 50.",
)
def delete_shop(
    shop_id: int,
    current_user: User = Depends(require_roles("root_admin")),
    db: Session = Depends(get_db),
):
    if current_user.role != "root_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found",
        )

    if shop.sage_sync_status in ("synced", SageSyncStatus.SYNCED.value, "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete this record because it has already been synced with Sage 50.",
        )

    # Check if shop has any synced orders
    synced_order = db.query(Order).filter(Order.shop_id == shop.id, Order.sage_sync_status == "synced").first()
    if synced_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete this record because it has already been synced with Sage 50.",
        )

    # Delete any unsynced orders and order items for this shop
    shop_orders = db.query(Order).filter(Order.shop_id == shop.id).all()
    for o in shop_orders:
        db.query(OrderItem).filter(OrderItem.order_id == o.id).delete(synchronize_session=False)
        db.delete(o)

    user_id = shop.user_id
    db.delete(shop)

    # Clean up associated user account if role is shop_owner
    shop_user = db.get(User, user_id)
    if shop_user and shop_user.role == "shop_owner":
        db.delete(shop_user)

    db.commit()

    return {"status": "success", "message": f"Shop {shop_id} deleted successfully"}

