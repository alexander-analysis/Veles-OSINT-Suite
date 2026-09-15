"""analyst watchlists

Revision ID: 008
Revises: 007
Create Date: 2026-09-15 22:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('watchlist_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('key', sa.String(length=300), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('alert', sa.Boolean(), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(), nullable=True),
    sa.Column('last_hit_at', sa.DateTime(), nullable=True),
    sa.Column('hit_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watchlist_items_active'), ['active'], unique=False)
        batch_op.create_index(batch_op.f('ix_watchlist_items_kind'), ['kind'], unique=False)
        batch_op.create_index('ix_watchlist_items_kind_key', ['kind', 'key'], unique=True)
        batch_op.create_index(batch_op.f('ix_watchlist_items_last_hit_at'), ['last_hit_at'], unique=False)

    op.create_table('watchlist_hits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('record_type', sa.String(length=40), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=True),
    sa.Column('summary', sa.String(length=300), nullable=True),
    sa.Column('href', sa.String(length=200), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['watchlist_items.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('watchlist_hits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watchlist_hits_item_id'), ['item_id'], unique=False)
        batch_op.create_index('ix_watchlist_hits_item_record', ['item_id', 'record_type', 'record_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_watchlist_hits_timestamp'), ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_table('watchlist_hits')
    op.drop_table('watchlist_items')
