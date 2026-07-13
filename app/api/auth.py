from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.database import get_db
from app.models.user import User, UserRole
from app.models.shop import Shop, ShopApprovalStatus, SageSyncStatus
from app.schemas.auth import LoginRequest, MeResponse, SignupRequest, TokenResponse, RegisterRequest, ChangePasswordRequest
from app.utils.security import (
    create_access_token,
    hash_password,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post(
    "/signup",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(payload: SignupRequest, db: Annotated[Session, Depends(get_db)]) -> User:
    email = normalize_email(payload.email)
    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        ) from exc

    db.refresh(user)
    return user


@router.post(
    "/register",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]) -> User:
    email = normalize_email(payload.email)
    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    # 1. Create the user as a shop owner
    user = User(
        name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=UserRole.SHOP_OWNER.value,
    )
    db.add(user)
    try:
        db.flush()  # flush to get user.id
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        ) from exc

    # Autogenerate account_ref starting with 'OR1'
    all_refs = db.query(Shop.account_ref).filter(Shop.account_ref.like("OR1%")).all()
    max_num = 0
    has_refs = False
    for ref_tuple in all_refs:
        ref = ref_tuple[0]
        if ref and len(ref) > 3:
            try:
                # Slice first 3 characters (OR1) and parse the rest as integer
                val = int(ref[3:])
                if val > max_num:
                    max_num = val
                has_refs = True
            except ValueError:
                continue

    if not has_refs:
        next_ref = "OR1001"
    else:
        next_ref = f"OR1{str(max_num + 1).zfill(3)}"

    # 2. Create the associated shop
    shop = Shop(
        user_id=user.id,
        company_name=payload.shop.company_name.strip(),
        phone_number=payload.shop.phone_number.strip(),
        address=payload.shop.address.strip(),
        address_line_2=(
            payload.shop.address_line_2.strip()
            if payload.shop.address_line_2
            else None
        ),
        postcode=payload.shop.postcode.strip(),
        city=payload.shop.city.strip(),
        country=payload.shop.country.strip(),
        company_registration_number=(
            payload.shop.company_registration_number.strip()
            if payload.shop.company_registration_number
            else None
        ),
        fax=(
            payload.shop.fax.strip()
            if payload.shop.fax
            else None
        ),
        website=(
            payload.shop.website.strip()
            if payload.shop.website
            else None
        ),
        account_ref=next_ref,
        approval_status=ShopApprovalStatus.PENDING.value,
        sage_sync_status=SageSyncStatus.PENDING.value,
    )
    db.add(shop)
    
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create shop registration: {str(exc)}",
        )

    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    identifier = payload.email.strip()
    
    # Lookup user by email OR shop phone_number OR shop account_ref
    user = db.query(User).outerjoin(Shop).filter(
        (User.email == identifier.lower()) |
        (Shop.phone_number == identifier) |
        (Shop.account_ref == identifier.upper())
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=MeResponse)
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change user password",
    description="Allows currently authenticated user to change their password."
)
def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        )
        
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New passwords do not match",
        )
        
    current_user.password_hash = hash_password(payload.new_password)
    if current_user.must_change_password:
        current_user.must_change_password = False
        
    db.commit()
    return {"detail": "Password updated successfully"}
