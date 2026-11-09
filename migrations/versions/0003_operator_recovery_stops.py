"""Persist operator stops independently of transient recovery claims."""
from alembic import op
import sqlalchemy as sa
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('payments',sa.Column('recovery_stop_reason',sa.String(),nullable=True))
    op.add_column('payments',sa.Column('recovery_stopped_at',sa.DateTime(),nullable=True))


def downgrade():
    raise RuntimeError('Operator stop history must not be discarded; use a reviewed backup restore')
