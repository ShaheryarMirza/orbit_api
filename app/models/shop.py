from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Boolean, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class ShopApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SageSyncStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"


class Shop(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    company_name = Column(String(255), nullable=False)
    phone_number = Column(String(50), nullable=False)
    contact_name = Column(String(255), nullable=True)
    telephone_2 = Column(String(50), nullable=True)
    telephone_3 = Column(String(50), nullable=True)
    address = Column(String(500), nullable=False)
    address_line_2 = Column(String(255), nullable=True)
    postcode = Column(String(20), nullable=False)
    city = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    company_registration_number = Column(String(50), nullable=True)
    fax = Column(String(50), nullable=True)
    website = Column(String(255), nullable=True)
    approval_status = Column(
        String(20),
        nullable=False,
        default=ShopApprovalStatus.PENDING.value,
        server_default=ShopApprovalStatus.PENDING.value,
    )
    is_approved = Column(Boolean, nullable=False, default=False, server_default="false")
    needs_sage_sync = Column(Boolean, nullable=False, default=False, server_default="false")
    sage_customer_id = Column(String(100), nullable=True)
    account_ref = Column(String(100), nullable=False, unique=True, index=True)
    sage_sync_status = Column(
        String(20),
        nullable=False,
        default=SageSyncStatus.PENDING.value,
        server_default=SageSyncStatus.PENDING.value,
    )
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

    user = relationship("User", back_populates="shop")
    orders = relationship("Order", back_populates="shop")

    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_shops_approval_status_allowed",
        ),
        CheckConstraint(
            "sage_sync_status IN ('pending', 'synced', 'failed')",
            name="ck_shops_sage_sync_status_allowed",
        ),
    )
