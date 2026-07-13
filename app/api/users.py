from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import SalespersonCreate, AdminCreate
from app.schemas.auth import MeResponse
from app.utils.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin-users"])

@router.post(
    "/create-admin",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new admin user",
    description="Only existing administrators can create admin accounts."
)
def create_admin(
    payload: AdminCreate,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    existing_user = db.query(User).filter(User.email == payload.email.strip().lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    new_admin = User(
        name=payload.full_name.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        role="admin",
        is_active=True,
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    return new_admin


@router.post(
    "/salespersons",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new salesperson user",
    description="Only administrators can create salesperson accounts."
)
def create_salesperson(
    payload: SalespersonCreate,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    existing_user = db.query(User).filter(User.email == payload.email.strip().lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    new_salesperson = User(
        name=payload.full_name.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        role="salesperson",
        is_active=True,
    )
    db.add(new_salesperson)
    db.commit()
    db.refresh(new_salesperson)
    return new_salesperson


@router.get(
    "/salespersons",
    response_model=list[MeResponse],
    summary="Get list of all salesperson users",
    description="Only administrators can retrieve the list of salesperson accounts."
)
def list_salespersons(
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    return db.query(User).filter(User.role == "salesperson").all()


@router.get(
    "/admins",
    response_model=list[MeResponse],
    summary="Get list of all admin users",
    description="Only administrators can retrieve the list of admin accounts."
)
def list_admins(
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    return db.query(User).filter(User.role == "admin").all()


@router.get(
    "/shops/pending",
    summary="Get list of all pending shop approvals",
    description="Only administrators can retrieve the list of pending shop accounts."
)
def list_pending_shops(
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
):
    from app.models.shop import Shop
    results = db.query(Shop, User).join(User, Shop.user_id == User.id).filter(Shop.is_approved == False).all()
    
    return [
        {
            "id": shop.id,
            "company_name": shop.company_name,
            "phone_number": shop.phone_number,
            "email": user.email,
            "account_ref": shop.account_ref
        }
        for shop, user in results
    ]


@router.patch(
    "/shops/{shop_id}/approve",
    summary="Approve a shop account",
    description="Only administrators can approve shop accounts."
)
def approve_shop(
    shop_id: int,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
):
    from app.models.shop import Shop, ShopApprovalStatus
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found",
        )
    
    shop.is_approved = True
    shop.approval_status = ShopApprovalStatus.APPROVED.value
    db.commit()
    return {"detail": "Shop approved successfully"}
