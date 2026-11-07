"""Bounded operator case search and a safe, readable event timeline."""

import json
import re

from app.models.models import AuditLog, Payment


EVENTS = {
    'decision_features':('Model inputs recorded','Observed history and executed-attempt features were saved.'),
    'executed':('Recovery checkout created','A recovery checkout was recorded.'),
    'human_approved_executed':('Operator approved checkout','The operator explicitly chose a recovery action.'),
    'escalated':('Waiting for operator','Automatic execution stopped for human assessment.'),
    'webhook_processed':('Provider event processed','A signed provider event finished processing.'),
    'recovered':('Recovery verified','Provider evidence settled this case as recovered.'),
    'attempt_failed':('Recovery attempt failed','A terminal failure was observed for an earlier action.'),
    'human_review_expired':('Review expired','The approval deadline passed without automatic execution.'),
    'reconciliation_settled':('Outcome reconciled','An operator verified the existing provider resource.'),
    'closed_unrecovered':('Case closed','No further eligible recovery action was executed.'),
    'skipped':('No action executed','The case or proposed action did not pass recovery rules.'),
}


def find_live_cases(db, search='', status='All statuses', limit=200):
    if not 1 <= limit <= 500 or len(search)>128:
        raise ValueError('Use a search up to 128 characters and a limit of 1..500')
    query=db.query(Payment).filter(Payment.payment_id.startswith('pay_', autoescape=True))
    if search.strip():
        query=query.filter(Payment.payment_id.contains(search.strip(), autoescape=True))
    if status!='All statuses':
        query=query.filter(Payment.status==status)
    return query.order_by(Payment.created_at.desc(),Payment.payment_id).limit(limit).all()


def case_timeline(db,payment_id,limit=200):
    if not 1 <= limit <= 500:
        raise ValueError('Timeline limit must be 1..500')
    rows=db.query(AuditLog).filter_by(payment_id=payment_id).order_by(
        AuditLog.timestamp.desc(),AuditLog.id.desc()).limit(limit).all()
    result=[]
    for row in reversed(rows):
        label,summary=EVENTS.get(row.event_type,('Additional case event','An additional case event was recorded.'))
        try:
            payload=json.loads(row.payload_json or '{}')
        except (TypeError,json.JSONDecodeError):
            payload={}
        if not isinstance(payload,dict):payload={}
        reference=next((payload.get(key) for key in ('provider_id','payment_link_id','order_id')
                        if isinstance(payload.get(key),str) and re.fullmatch(r'(?:pay|plink|order)_[A-Za-z0-9]{1,64}',payload[key])), '')
        result.append({'Time (UTC)':row.timestamp.isoformat(timespec='seconds'),
                       'Event':label,'Summary':summary,'Provider reference':reference})
    return result
