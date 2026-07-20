from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.database import get_db
from app.models.user import User
from app.models.shop import Shop
from app.models.password_reset_request import PasswordResetRequest
from app.schemas.password_request import PasswordResetRequestResponse, PasswordResetResolveRequest
from app.utils.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin-password-requests"])


@router.get(
    "/password-requests",
    response_model=list[PasswordResetRequestResponse],
    summary="Get all pending password reset requests",
)
def get_pending_password_requests(
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[PasswordResetRequest]:
    return (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.status == "pending")
        .order_by(PasswordResetRequest.created_at.desc())
        .all()
    )


@router.patch(
    "/password-requests/{request_id}/resolve",
    response_model=PasswordResetRequestResponse,
    summary="Resolve a password reset request, optionally updating the user's password",
)
def resolve_password_request(
    request_id: int,
    payload: PasswordResetResolveRequest,
    current_user: Annotated[User, Depends(require_roles("admin"))],
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetRequest:
    req = db.get(PasswordResetRequest, request_id)
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Password reset request not found",
        )

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset request is already resolved",
        )

    # If new password is provided, reset it
    if payload.new_password:
        # Find user by email
        user = db.query(User).filter(User.email == req.email).first()
        if not user:
            # Fallback: check via Shop account_ref
            shop = db.query(Shop).filter(Shop.account_ref == req.account_ref).first()
            if shop:
                user = db.query(User).filter(User.id == shop.user_id).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user account found for email '{req.email}' or account reference '{req.account_ref}'",
            )

        # Update password
        user.password_hash = hash_password(payload.new_password)
        # Ensure must_change_password is False as per request 7
        user.must_change_password = False

    # Mark request as resolved
    req.status = "resolved"
    db.commit()
    db.refresh(req)
    return req
