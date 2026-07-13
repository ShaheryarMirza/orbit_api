"""Add order reference fields

Revision ID: 20260610_0006
Revises: 20260608_0005
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260610_0006"
down_revision: Union[str, Sequence[str], None] = "20260608_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("order_number", sa.String(length=20), nullable=True))
    op.add_column(
        "orders",
        sa.Column("customer_reference", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("internal_notes", sa.String(length=1000), nullable=True),
    )
    op.create_index(
        "ix_orders_order_number",
        "orders",
        ["order_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_column("orders", "internal_notes")
    op.drop_column("orders", "customer_reference")
    op.drop_column("orders", "order_number")
