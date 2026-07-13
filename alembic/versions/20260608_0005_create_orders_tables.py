"""Create orders tables

Revision ID: 20260608_0005
Revises: 20260608_0004
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0005"
down_revision: Union[str, Sequence[str], None] = "20260608_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_by_role", sa.String(length=20), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_type", sa.String(length=20), nullable=True),
        sa.Column("discount_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("final_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="placed",
            nullable=False,
        ),
        sa.Column("sage_sales_order_id", sa.String(length=100), nullable=True),
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
            "discount_type IS NULL OR discount_type IN ('fixed', 'percentage')",
            name="ck_orders_discount_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('placed', 'cancelled')",
            name="ck_orders_status_allowed",
        ),
        sa.CheckConstraint(
            "sage_sync_status IN ('pending', 'processing', 'synced', 'failed')",
            name="ck_orders_sage_sync_status_allowed",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_created_by_user_id", "orders", ["created_by_user_id"])
    op.create_index("ix_orders_shop_id", "orders", ["shop_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_product_id", table_name="order_items")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_shop_id", table_name="orders")
    op.drop_index("ix_orders_created_by_user_id", table_name="orders")
    op.drop_table("orders")
