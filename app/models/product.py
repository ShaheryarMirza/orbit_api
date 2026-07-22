from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category_id = Column(
        Integer,
        ForeignKey("categories.id"),
        nullable=True,
        index=True,
    )
    subcategory_id = Column(
        Integer,
        ForeignKey("subcategories.id"),
        nullable=True,
        index=True,
    )
    product_code = Column(String(100), nullable=False, unique=True, index=True)
    product_name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    image_url = Column(String(255), nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    vat_rate = Column(Float, nullable=False, default=20.0, server_default="20.0")
    quantity = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    sage_sync_status = Column(String(50), nullable=False, default="synced", server_default="synced")
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

    category = relationship("Category", back_populates="products")
    subcategory = relationship("SubCategory", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
