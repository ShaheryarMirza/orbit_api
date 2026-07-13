"""Create products table

Revision ID: 20260608_0004
Revises: 20260608_0003
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0004"
down_revision: Union[str, Sequence[str], None] = "20260608_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "quantity",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        sa.ForeignKeyConstraint(["subcategory_id"], ["subcategories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_products_product_code",
        "products",
        ["product_code"],
        unique=True,
    )
    op.create_index(
        "ix_products_subcategory_id",
        "products",
        ["subcategory_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_subcategory_id", table_name="products")
    op.drop_index("ix_products_product_code", table_name="products")
    op.drop_table("products")
