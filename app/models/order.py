from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class DiscountType(str, Enum):
    FIXED = "fixed"
    PERCENTAGE = "percentage"


class OrderStatus(str, Enum):
    PLACED = "placed"
    CANCELLED = "cancelled"


class OrderSageSyncStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SYNCED = "synced"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_number = Column(String(20), nullable=True, unique=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_by_role = Column(String(20), nullable=False)
    salesperson_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    customer_reference = Column(String(255), nullable=True)
    internal_notes = Column(String(1000), nullable=True)
    subtotal = Column(Numeric(12, 2), nullable=False)
    discount_type = Column(String(20), nullable=True)
    discount_value = Column(Numeric(12, 2), nullable=True)
    discount_amount = Column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        server_default="0",
    )
    final_total = Column(Numeric(12, 2), nullable=False)
    total_vat = Column(Float, nullable=False, default=0.0, server_default="0.0")
    status = Column(
        String(20),
        nullable=False,
        default=OrderStatus.PLACED.value,
        server_default=OrderStatus.PLACED.value,
    )
    sage_sales_order_id = Column(String(100), nullable=True)
    sage_order_number = Column(String(100), nullable=True)
    account_ref = Column(String(100), nullable=True)
    sage_sync_status = Column(
        String(20),
        nullable=False,
        default=OrderSageSyncStatus.PENDING.value,
        server_default=OrderSageSyncStatus.PENDING.value,
    )
    sync_notes = Column(String(1000), nullable=True)
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

    shop = relationship("Shop", back_populates="orders")
    created_by = relationship("User", foreign_keys=[created_by_user_id], back_populates="orders_created")
    salesperson = relationship("User", foreign_keys=[salesperson_id])
    items = relationship("OrderItem", back_populates="order")

    __table_args__ = (
        CheckConstraint(
            "discount_type IS NULL OR discount_type IN ('fixed', 'percentage')",
            name="ck_orders_discount_type_allowed",
        ),
        CheckConstraint(
            "status IN ('placed', 'cancelled')",
            name="ck_orders_status_allowed",
        ),
        CheckConstraint(
            "sage_sync_status IN ('pending', 'processing', 'synced', 'failed')",
            name="ck_orders_sage_sync_status_allowed",
        ),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    product_code = Column(String(100), nullable=False)
    product_name = Column(String(255), nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)
    vat_rate = Column(Float, nullable=False, default=20.0, server_default="20.0")
    vat_amount = Column(Float, nullable=False, default=0.0, server_default="0.0")

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")
