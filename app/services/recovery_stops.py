"""Persistent operator stop signals; never expire another financial operation's claim."""
import json
from datetime import datetime
from app.models.models import Payment,OriginalOrderRecovery,RecoveryReservation,Action,ReviewStatus,AuditLog
from app.services.original_orders import bind_original_order
from app.services.reservations import reserve_recovery,finish_recovery

REASONS={'customer_opt_out':'Customer opted out','merchant_cancelled':'Merchant cancelled',
         'fraud_concern':'Fraud concern','operator_stop':'Operator stop'}


def stop_followup(db,payment_id,operator,reason):
    if not isinstance(operator,str) or not operator.strip() or len(operator)>64 or reason not in REASONS:
        return {'status':'blocked','message':'Authenticated operator and a supported stop reason are required.'}
    payment=db.get(Payment,payment_id)
    if not payment or not payment_id.startswith('pay_'):
        return {'status':'blocked','message':'Choose an existing Test Mode payment case.'}
    scope=bind_original_order(db,payment)
    query=db.query(Payment).filter(Payment.order_id==payment.order_id) if payment.order_id else db.query(Payment).filter_by(payment_id=payment_id)
    ids=[p.payment_id for p in query.all()]
    changed=query.filter(Payment.recovery_stop_reason.is_(None)).update(
        {'recovery_stop_reason':reason,'recovery_stopped_at':datetime.utcnow()},synchronize_session=False)
    if scope and scope.state=='active':scope.state='operator_stopped'
    if changed:
        db.add(AuditLog(payment_id=payment_id,event_type='followup_stopped',
            reason='Operator recorded a persistent recovery stop',
            payload_json=json.dumps({'operator':operator,'stop_reason':reason,'affected_attempts':changed})))
    db.commit();db.expire_all()
    owner_id=scope.payment_id if scope and scope.payment_id else payment_id
    claim=db.get(RecoveryReservation,owner_id)
    if claim and claim.state not in {'pending_review','awaiting_outcome'}:
        return {'status':'stop_recorded','message':'Stop recorded. The active or uncertain operation remains owned; an in-flight provider request may still finish. No future collection is authorized.'}
    owner=reserve_recovery(db,owner_id,claim.state if claim else None)
    if owner is None:
        return {'status':'stop_recorded','message':'Stop recorded; another operation still owns the case.'}
    try:
        db.expire_all()
        target=db.get(Payment,owner_id)
        if target and target.status=='failed':target.status='closed_unrecovered'
        db.query(Action).filter(Action.payment_id.in_(ids),Action.review_status==ReviewStatus.pending).update(
            {'review_status':ReviewStatus.expired,'reason':'Operator stopped further recovery'},synchronize_session=False)
        db.commit()
    finally:
        finish_recovery(db,owner_id,owner)
    return {'status':'stopped','message':'Further recovery stopped. Previously issued links may still accept payment; review unpaid old links separately. No refund or cancellation was sent.'}
