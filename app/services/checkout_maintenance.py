"""Explicit Test Mode cleanup of unpaid links belonging to closed cases."""

import json

from app.config import settings
from app.models.models import Payment,RecoveryExecution,RecoveryReservation,AuditLog
from app.services.razorpay_client import client
from app.services.reservations import reserve_recovery,finish_recovery


class CheckoutCleanupError(ValueError):
    pass


def check_old_link(db,payment_id,execution_id):
    payment=db.get(Payment,payment_id);execution=db.get(RecoveryExecution,execution_id)
    if (not payment or payment.status not in {'recovered','closed_unrecovered'} or not execution
            or execution.payment_id!=payment_id or execution.provider_type!='payment_link'):
        raise CheckoutCleanupError('Choose a recorded payment link belonging to a closed case.')
    resource=client.payment_link.fetch(execution.provider_id)
    if (resource.get('id')!=execution.provider_id or resource.get('amount')!=execution.amount_paise
            or resource.get('currency')!=execution.currency):
        raise CheckoutCleanupError('Provider resource does not match the recorded case.')
    return {'provider_id':execution.provider_id,'status':resource.get('status','unknown'),
            'can_cancel':resource.get('status')=='created' and resource.get('amount_paid')==0,
            'execution_id':execution.id}


def cancel_old_link(db,payment_id,execution_id,operator):
    if not settings.razorpay_key_id.startswith('rzp_test_'):
        return {'status':'blocked','message':'This cleanup control supports Test Mode only.'}
    if not isinstance(operator,str) or not operator.strip() or len(operator)>64:
        return {'status':'blocked','message':'Authenticated operator required.'}
    payment=db.get(Payment,payment_id)
    if not payment or payment.status not in {'recovered','closed_unrecovered'}:
        return {'status':'blocked','message':'Active cases cannot be cancelled through closed-case cleanup.'}
    owner=reserve_recovery(db,payment_id)
    if owner is None:
        return {'status':'blocked','message':'Another case operation is active. Check again later.'}
    try:
        db.expire_all()
        evidence=check_old_link(db,payment_id,execution_id)
        if not evidence['can_cancel']:
            return {'status':'not_needed','message':'Link is paid, partly paid or already inactive; no cancellation was sent.'}
        response=client.payment_link.cancel(evidence['provider_id'])
        execution=db.get(RecoveryExecution,execution_id)
        if (response.get('id')!=execution.provider_id or response.get('status')!='cancelled'
                or response.get('amount')!=execution.amount_paise or response.get('currency')!=execution.currency):
            raise CheckoutCleanupError('Provider cancellation is not confirmed')
        db.add(AuditLog(payment_id=payment_id,event_type='old_link_cancelled',
            reason='Operator cancelled an unpaid Test Mode link for a closed case',
            payload_json=json.dumps({'execution_id':execution_id,'provider_id':execution.provider_id})))
        db.commit()
        return {'status':'cancelled','message':'Unpaid old link cancelled and recorded.'}
    except Exception:
        db.rollback()
        db.add(AuditLog(payment_id=payment_id,event_type='old_link_unconfirmed',
            reason='Link cleanup not confirmed; fetch provider status before retrying',
            payload_json=json.dumps({'execution_id':execution_id})))
        db.commit()
        return {'status':'unconfirmed','message':'Cancellation was not confirmed. Check the provider status again; no recovery or refund was created.'}
    finally:
        # Cancelling an unpaid link never creates a charge. A later attempt
        # always re-fetches state, including after an accepted response is lost.
        finish_recovery(db,payment_id,owner)
