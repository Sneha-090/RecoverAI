"""Bounded follow-up for due provider cases, preserving exclusive case ownership."""

from datetime import datetime,timedelta

from app.db.session import SessionLocal
from app.config import settings
from app.models.models import RecoveryReservation,Payment
from app.services.execution import _run_reserved,_observe_outcome
from app.services.reservations import RecoveryInProgress


def poll_pending_outcomes(limit=25,min_age_seconds=60,session_factory=None,now=None):
    if not 1<=limit<=100 or not 10<=min_age_seconds<=86400:
        raise ValueError('Use a batch limit of 1..100 and age of 10..86400 seconds')
    if not settings.razorpay_key_id.startswith('rzp_test_'):
        raise ValueError('The outcome follow-up worker supports Test Mode only')
    factory=session_factory or SessionLocal
    now=now or datetime.utcnow()
    with factory() as db:
        ids=[row[0] for row in db.query(RecoveryReservation.payment_id).join(
            Payment,Payment.payment_id==RecoveryReservation.payment_id).filter(
            RecoveryReservation.state=='awaiting_outcome',
            RecoveryReservation.updated_at<=now-timedelta(seconds=min_age_seconds),
            Payment.status=='failed',Payment.payment_id.startswith('pay_',autoescape=True),
        ).order_by(RecoveryReservation.updated_at,RecoveryReservation.payment_id).limit(limit).all()]
    summary={'selected':len(ids),'recovered':0,'pending':0,'advanced':0,'blocked':0,'errors':0}
    for payment_id in ids:
        with factory() as db:
            payment=db.get(Payment,payment_id)
            claim=db.get(RecoveryReservation,payment_id)
            if not payment or payment.status!='failed' or not claim or claim.state!='awaiting_outcome':
                summary['blocked']+=1
                continue
            try:
                result=_run_reserved(db,payment_id,lambda:_observe_outcome(
                    db,payment,waiting_state='awaiting_outcome'),expected_state='awaiting_outcome')
                state=result.get('status')
                key='recovered' if state=='recovered' else 'pending' if state=='awaiting_outcome' else 'advanced'
                summary[key]+=1
            except RecoveryInProgress:
                summary['blocked']+=1
            except Exception:
                # Normal service handling preserves ambiguous cases for reconciliation.
                # Never emit payloads, provider exceptions, contacts or secrets.
                db.rollback();summary['errors']+=1
    return summary
