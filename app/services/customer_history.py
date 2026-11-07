"""Derive history from verified, finalized cases instead of stale customer counters."""

from datetime import datetime, timezone

from app.models.models import Payment, Outcome, AuditLog

DEFAULT_PAST_RATE = 0.5


def customer_history(db, customer_id, current_payment_id=None, as_of=None):
    as_of = as_of or datetime.utcnow()
    if as_of.tzinfo is not None:
        as_of = as_of.astimezone(timezone.utc).replace(tzinfo=None)
    snapshot = {'linked_customer': bool(customer_id), 'finalized_cases':0,
                'recovered_cases':0, 'past_rate':DEFAULT_PAST_RATE, 'uses_default':True}
    if not customer_id:
        return snapshot
    cases = db.query(Payment).filter(Payment.customer_id == customer_id,
        Payment.payment_id != (current_payment_id or ''), Payment.created_at <= as_of,
        Payment.status.in_(['recovered','closed_unrecovered'])).all()
    ids = [row.payment_id for row in cases]
    if not ids:
        return snapshot
    successful = {row.payment_id for row in db.query(Outcome).filter(
        Outcome.payment_id.in_(ids), Outcome.observed_result=='success', Outcome.observed_at<=as_of).all()}
    closed = {row.payment_id for row in db.query(AuditLog).filter(
        AuditLog.payment_id.in_(ids), AuditLog.event_type.in_(['closed_unrecovered','human_review_expired']),
        AuditLog.timestamp<=as_of).all()}
    finalized = [row for row in cases if (row.status=='recovered' and row.payment_id in successful)
                 or (row.status=='closed_unrecovered' and row.payment_id in closed)]
    recovered = sum(row.status=='recovered' for row in finalized)
    if finalized:
        snapshot.update(finalized_cases=len(finalized), recovered_cases=recovered,
                        past_rate=recovered/len(finalized), uses_default=False)
    return snapshot
