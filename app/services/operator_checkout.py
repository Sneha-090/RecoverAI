"""Verified Test Mode checkout configuration shared by authenticated operator surfaces."""
import re
from app.config import settings
from app.models.models import Payment,RecoveryExecution,RecoveryReservation,RecoveryIntent
from app.services.eligibility import is_recovery_eligible
from app.services.original_orders import original_order_eligibility,read_original_order,OriginalOrderVerificationError
from app.services.razorpay_client import client,require_test_mode


class CheckoutUnavailable(ValueError):
    pass


def operator_checkout_config(db,order_id):
    require_test_mode()
    if not isinstance(order_id,str) or not re.fullmatch(r'order_[A-Za-z0-9]{1,64}',order_id):
        raise CheckoutUnavailable('Enter a valid Razorpay order ID')
    order=client.order.fetch(order_id)
    if (not isinstance(order,dict) or order.get('id')!=order_id or order.get('currency')!='INR'
            or type(order.get('amount')) is not int or not 1<=order['amount']<=1_000_000_000):
        raise CheckoutUnavailable('Provider order identity, amount or currency does not match')
    if (order.get('status') not in {'created','attempted'} or type(order.get('amount_paid')) is not int or order['amount_paid']!=0
            or type(order.get('attempts')) is not int or not 0<=order['attempts']<=100
            or type(order.get('amount_due')) is not int or order['amount_due']!=order['amount']):
        raise CheckoutUnavailable('This order is already paid or needs investigation')
    execution=db.query(RecoveryExecution).filter_by(provider_type='order',provider_id=order_id).first()
    notes=order.get('notes') or {};receipt=order.get('receipt') or ''
    is_recovery=bool(execution or isinstance(notes,dict) and notes.get('recoverai_intent_id')
                     or isinstance(receipt,str) and receipt.startswith(('retry_','human_')))
    if is_recovery:
        payment=db.get(Payment,execution.payment_id) if execution else None
        claim=db.get(RecoveryReservation,execution.payment_id) if execution else None
        if (not payment or not claim or claim.state!='awaiting_outcome'
                or not is_recovery_eligible(payment)[0] or not original_order_eligibility(db,payment)[0]
                or execution.amount_paise!=order['amount'] or execution.currency!=order['currency']):
            raise CheckoutUnavailable('This recovery checkout is no longer active; review the case')
        if payment.order_id:
            try:
                if read_original_order(payment)['status']!='open':
                    raise CheckoutUnavailable('The original order is already paid; no new recovery checkout')
            except OriginalOrderVerificationError:
                raise CheckoutUnavailable('Original order verification needs investigation; no checkout opened') from None
    else:
        originals=db.query(Payment).filter_by(order_id=order_id).all()
        for payment in originals:
            if (not is_recovery_eligible(payment)[0] or not original_order_eligibility(db,payment)[0]
                    or db.query(RecoveryIntent).filter_by(payment_id=payment.payment_id).first()):
                raise CheckoutUnavailable('Original-order follow-up is stopped or recovery has already been issued')
    if order.get('attempts',0):
        collection=client.order.payments(order_id)
        attempts=collection.get('items') if isinstance(collection,dict) else None
        if (not isinstance(attempts,list) or len(attempts)>100 or len(attempts)!=order['attempts']
                or any(not isinstance(p,dict) or p.get('order_id')!=order_id or p.get('status')!='failed' for p in attempts)):
            raise CheckoutUnavailable('A payment is pending or its history needs investigation')
    return {'key_id':settings.razorpay_key_id,'order_id':order_id,'amount_paise':order['amount'],'currency':'INR',
            'checkout_note':'A fresh checkout requires an explicit payment by the customer; no automatic debit is performed.'}
