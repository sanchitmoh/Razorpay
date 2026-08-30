"""add batch_id to bank_entry and ledger_entry

Revision ID: 26672c42bab3
Revises: e776e428dcf1
Create Date: 2026-08-26 00:36:41.995215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26672c42bab3'
down_revision: Union[str, Sequence[str], None] = 'e776e428dcf1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using batch_alter_table for SQLite compatibility."""
    with op.batch_alter_table('bank_entry', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_id', sa.Uuid(), nullable=False))
        batch_op.create_index(batch_op.f('ix_bank_entry_batch_id'), ['batch_id'], unique=False)
        batch_op.create_foreign_key('fk_bank_entry_batch_id', 'batch', ['batch_id'], ['id'])

    with op.batch_alter_table('ledger_entry', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_id', sa.Uuid(), nullable=False))
        batch_op.create_index(batch_op.f('ix_ledger_entry_batch_id'), ['batch_id'], unique=False)
        batch_op.create_foreign_key('fk_ledger_entry_batch_id', 'batch', ['batch_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema using batch_alter_table."""
    with op.batch_alter_table('ledger_entry', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ledger_entry_batch_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_ledger_entry_batch_id'))
        batch_op.drop_column('batch_id')

    with op.batch_alter_table('bank_entry', schema=None) as batch_op:
        batch_op.drop_constraint('fk_bank_entry_batch_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_bank_entry_batch_id'))
        batch_op.drop_column('batch_id')
