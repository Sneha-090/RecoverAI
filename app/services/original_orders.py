"""Permanent ownership of original provider orders, shared by all payment attempts."""

from sqlalchemy.exc import IntegrityError

from app.models.models import (
    Action, OriginalOrderRecovery, Payment, RecoveryExecution, RecoveryIntent, RecoveryReservation,
)


def bind_original_order(db, payment):
    if not payment.order_id:
        return None
    row = db.get(OriginalOrderRecovery, payment.order_id)
    if row is not None:
        return row
    attempts = db.query(Payment).filter_by(order_id=payment.order_id).order_by(
        Payment.created_at, Payment.payment_id).all()
    identities = [p.payment_id for p in attempts]
    worked = set()
    for model in (Action, RecoveryExecution, RecoveryIntent, RecoveryReservation):
        worked.update(p[0] for p in db.query(model.payment_id).filter(model.payment_id.in_(identities)).distinct())
    # Legacy actions/claims win over a later webhook. Multiple prior owners need review.
    owner = next(iter(worked)) if len(worked) == 1 else attempts[0].payment_id
    candidate = OriginalOrderRecovery(order_id=payment.order_id,
                                     payment_id=None if len(worked) > 1 else owner,
                                     state='ambiguous' if len(worked) > 1 else 'active')
    try:
        db.add(candidate)
        db.commit()  # Must be durable before any provider creation or review.
    except IntegrityError:
        db.rollback()
        if db.get(OriginalOrderRecovery, payment.order_id) is None:
            raise
    return db.get(OriginalOrderRecovery, payment.order_id)


def original_order_eligibility(db, payment):
    row = bind_original_order(db, payment)
    if row is None:
        return True, 'No original provider order reference'
    db.refresh(row)
    if row.state == 'ambiguous' or row.payment_id is None:
        return False, 'Original order has multiple legacy recovery owners; investigation required'
    if row.payment_id != payment.payment_id:
        return False, f'Original order recovery belongs to case {row.payment_id}; no independent follow-up'
    if row.state != 'active':
        return False, f'Original order recovery is {row.state}; no further collection'
    return True, 'Canonical original order recovery owner'
