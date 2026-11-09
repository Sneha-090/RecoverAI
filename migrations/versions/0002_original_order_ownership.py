"""Bind each original order to a single recovery case without merging ambiguous history."""

from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        'original_order_recoveries',
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('payment_id', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('captured_payment_id', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.payment_id']),
        sa.PrimaryKeyConstraint('order_id'),
    )
    connection = op.get_bind()
    payments = connection.execute(sa.text(
        'SELECT payment_id, order_id FROM payments WHERE order_id IS NOT NULL '
        "AND order_id != '' ORDER BY created_at, payment_id")).all()
    groups = {}
    for payment_id, order_id in payments:
        groups.setdefault(order_id, []).append(payment_id)
    worked = set()
    for name in ('actions', 'recovery_executions', 'recovery_intents', 'recovery_reservations'):
        worked.update(row[0] for row in connection.execute(sa.text('SELECT DISTINCT payment_id FROM ' + name)))
    for order_id, attempts in groups.items():
        prior = [p for p in attempts if p in worked]
        connection.execute(table.insert().values(
            order_id=order_id, payment_id=None if len(prior) > 1 else prior[0] if prior else attempts[0],
            state='ambiguous' if len(prior) > 1 else 'active', created_at=datetime.utcnow(),
        ))


def downgrade():
    raise RuntimeError('Original-order ownership must not be discarded; use a reviewed backup restore')
