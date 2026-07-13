"""update_shop_model_sage_compliance

Revision ID: 329ae28d4988
Revises: 219d7b8375b4
Create Date: 2026-07-09 15:56:38.276954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '329ae28d4988'
down_revision: Union[str, Sequence[str], None] = '219d7b8375b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update orders table: add account_ref, copy data, drop sage_account_reference
    op.add_column('orders', sa.Column('account_ref', sa.String(length=100), nullable=True))
    op.execute("UPDATE orders SET account_ref = sage_account_reference")
    op.drop_column('orders', 'sage_account_reference')

    # 2. Update shops table: add company_name as nullable, copy data, make non-nullable, drop name
    op.add_column('shops', sa.Column('company_name', sa.String(length=255), nullable=True))
    op.execute("UPDATE shops SET company_name = name")
    op.alter_column('shops', 'company_name', nullable=False)
    op.drop_column('shops', 'name')

    # 3. Update shops table: add country as nullable, set default, make non-nullable
    op.add_column('shops', sa.Column('country', sa.String(length=100), nullable=True))
    op.execute("UPDATE shops SET country = 'GB'")
    op.alter_column('shops', 'country', nullable=False)

    # 4. Update shops table: add account_ref as nullable, copy data or generate defaults, make non-nullable, drop old ref columns, add unique index
    op.add_column('shops', sa.Column('account_ref', sa.String(length=100), nullable=True))
    op.execute("UPDATE shops SET account_ref = COALESCE(sage_account_reference, sage_account_ref)")
    op.execute("UPDATE shops SET account_ref = 'OR1' || (1000 + id) WHERE account_ref IS NULL")
    op.alter_column('shops', 'account_ref', nullable=False)
    op.create_index(op.f('ix_shops_account_ref'), 'shops', ['account_ref'], unique=True)
    op.drop_column('shops', 'sage_account_ref')
    op.drop_column('shops', 'sage_account_reference')

    # 5. Update shops table: add optional columns
    op.add_column('shops', sa.Column('address_line_2', sa.String(length=255), nullable=True))
    op.add_column('shops', sa.Column('fax', sa.String(length=50), nullable=True))
    op.add_column('shops', sa.Column('website', sa.String(length=255), nullable=True))


def downgrade() -> None:
    # 1. Downgrade orders table
    op.add_column('orders', sa.Column('sage_account_reference', sa.VARCHAR(length=100), autoincrement=False, nullable=True))
    op.execute("UPDATE orders SET sage_account_reference = account_ref")
    op.drop_column('orders', 'account_ref')

    # 2. Downgrade shops table
    op.add_column('shops', sa.Column('name', sa.VARCHAR(length=255), autoincrement=False, nullable=True))
    op.execute("UPDATE shops SET name = company_name")
    op.alter_column('shops', 'name', nullable=False)
    op.drop_column('shops', 'company_name')

    op.add_column('shops', sa.Column('sage_account_reference', sa.VARCHAR(length=100), autoincrement=False, nullable=True))
    op.add_column('shops', sa.Column('sage_account_ref', sa.VARCHAR(length=100), autoincrement=False, nullable=True))
    op.execute("UPDATE shops SET sage_account_reference = account_ref")
    
    op.drop_index(op.f('ix_shops_account_ref'), table_name='shops')
    op.drop_column('shops', 'account_ref')
    op.drop_column('shops', 'website')
    op.drop_column('shops', 'fax')
    op.drop_column('shops', 'country')
    op.drop_column('shops', 'address_line_2')
