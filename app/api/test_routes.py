from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import require_roles
from app.models.user import User


router = APIRouter(prefix="/test", tags=["test"])


@router.get("/admin-only")
def admin_only(current_user: Annotated[User, Depends(require_roles("admin"))]) -> dict[str, str]:
    return {"message": "admin access granted"}


@router.get("/salesperson-only")
def salesperson_only(
    current_user: Annotated[User, Depends(require_roles("salesperson"))],
) -> dict[str, str]:
    return {"message": "salesperson access granted"}


@router.get("/shop-owner-only")
def shop_owner_only(
    current_user: Annotated[User, Depends(require_roles("shop_owner"))],
) -> dict[str, str]:
    return {"message": "shop owner access granted"}


@router.get("/admin-or-salesperson")
def admin_or_salesperson(
    current_user: Annotated[User, Depends(require_roles("admin", "salesperson"))],
) -> dict[str, str]:
    return {"message": "admin or salesperson access granted"}
