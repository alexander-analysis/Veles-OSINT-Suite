"""energy monitor: vessel dimensions and port-call draught snapshots

Revision ID: 005
Revises: 004
Create Date: 2026-09-15 13:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('vessels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('length_m', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('beam_m', sa.Float(), nullable=True))
    with op.batch_alter_table('port_call_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('draught_arrival', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('draught_departure', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('energy_facility_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_port_call_events_energy_facility_id'), ['energy_facility_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('port_call_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_port_call_events_energy_facility_id'))
        batch_op.drop_column('energy_facility_id')
        batch_op.drop_column('draught_departure')
        batch_op.drop_column('draught_arrival')
    with op.batch_alter_table('vessels', schema=None) as batch_op:
        batch_op.drop_column('beam_m')
        batch_op.drop_column('length_m')
