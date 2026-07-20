from sqlalchemy import Column, DateTime, Integer, String, func
from app.db.database import Base


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True)
    account_ref = Column(String(100), nullable=False)
    company_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone_number = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
