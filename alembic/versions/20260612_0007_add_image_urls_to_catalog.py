"""Add image urls to catalog

Revision ID: 20260612_0007
Revises: 20260610_0006
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260612_0007"
down_revision: Union[str, Sequence[str], None] = "20260610_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("image_url", sa.String(length=255), nullable=True))
    op.add_column("subcategories", sa.Column("image_url", sa.String(length=255), nullable=True))
    op.add_column("products", sa.Column("image_url", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "image_url")
    op.drop_column("subcategories", "image_url")
    op.drop_column("categories", "image_url")
