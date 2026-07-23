from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class UserRole(str, Enum):
    ROOT_ADMIN = "root_admin"
    ADMIN = "admin"
    SALESPERSON = "salesperson"
    SHOP_OWNER = "shop_owner"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('root_admin', 'admin', 'salesperson', 'shop_owner')",
            name="ck_users_role_allowed",
        ),
    )

    shop = relationship("Shop", back_populates="user", uselist=False)
    orders_created = relationship("Order", foreign_keys="[Order.created_by_user_id]", back_populates="created_by")

    @property
    def is_approved(self) -> bool:
        if self.role in ("admin", "salesperson"):
            return True
        if self.shop:
            return self.shop.is_approved
        return False
