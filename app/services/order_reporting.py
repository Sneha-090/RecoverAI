"""Order-level headline totals, separate from attempt-level decision distributions."""

from collections import defaultdict
from app.models.models import Payment,OriginalOrderRecovery
from app.services.action_reporting import SCOPES
from app.services.money import amount_paise


def build_order_summary(db,scope='Razorpay Test Mode'):
    if scope not in SCOPES:
        raise ValueError('Choose a supported data source')
    payments=db.query(Payment).filter(Payment.payment_id.startswith(SCOPES[scope],autoescape=True)).all()
    groups=defaultdict(list)
    for payment in payments:
        groups[('order',payment.order_id) if payment.order_id else ('payment',payment.payment_id)].append(payment)
    orders={row.order_id:row for row in db.query(OriginalOrderRecovery).filter(
        OriginalOrderRecovery.order_id.in_([key[1] for key in groups if key[0]=='order'])).all()}
    result={'payment_attempts':len(payments),'tracked_groups':len(groups),'known_orders':0,
            'standalone_payments':0,'recovered_groups':0,'recovered_amount':0,
            'paid_original_groups':0,'investigation_groups':0}
    recovered_paise=0
    for key,attempts in groups.items():
        result['known_orders' if key[0]=='order' else 'standalone_payments']+=1
        owner=orders.get(key[1]) if key[0]=='order' else None
        recovered=[p for p in attempts if p.status=='recovered']
        direct=any(p.status=='paid_original' for p in attempts) or bool(owner and owner.state=='paid_original')
        ambiguous=(len({amount_paise(p.amount) for p in attempts})!=1
                   or len(recovered)>1 or any(p.status=='needs_reconciliation' for p in attempts)
                   or bool(owner and owner.state=='ambiguous')
                   or bool(recovered and direct)
                   or bool(recovered and owner and owner.payment_id!=recovered[0].payment_id))
        if ambiguous:
            result['investigation_groups']+=1
        elif recovered:
            result['recovered_groups']+=1
            recovered_paise+=amount_paise(recovered[0].amount)
        elif direct:
            result['paid_original_groups']+=1
    result['recovered_amount']=recovered_paise/100
    return result
