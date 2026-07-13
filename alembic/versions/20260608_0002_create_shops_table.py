"""Create shops table

Revision ID: 20260608_0002
Revises: 20260607_0001
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0002"
down_revision: Union[str, Sequence[str], None] = "20260607_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("postcode", sa.String(length=20), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("company_registration_number", sa.String(length=50), nullable=True),
        sa.Column(
            "approval_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("sage_customer_id", sa.String(length=100), nullable=True),
        sa.Column("sage_account_ref", sa.String(length=100), nullable=True),
        sa.Column(
            "sage_sync_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_shops_approval_status_allowed",
        ),
        sa.CheckConstraint(
            "sage_sync_status IN ('pending', 'synced', 'failed')",
            name="ck_shops_sage_sync_status_allowed",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("shops")
