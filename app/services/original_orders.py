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

class OriginalOrderVerificationError(ValueError):
    pass


def read_original_order(payment, captured_payment_id=None):
    """Fresh provider evidence; never trust webhook amount/status or contact data."""
    from app.services.razorpay_client import client
    from app.services.money import amount_paise
    expected = amount_paise(payment.amount)
    try:
        order = client.order.fetch(payment.order_id)
        if (not isinstance(order, dict) or order.get('id') != payment.order_id
                or type(order.get('amount')) is not int or order['amount'] != expected
                or order.get('currency') != 'INR'):
            raise OriginalOrderVerificationError('Original order identity, amount or currency mismatch')
        paid, due = order.get('amount_paid'), order.get('amount_due')
        if type(paid) is not int or type(due) is not int or paid < 0 or due < 0 or paid + due != expected:
            raise OriginalOrderVerificationError('Original order paid amounts need investigation')
        if order.get('status') not in {'created', 'attempted', 'paid'}:
            raise OriginalOrderVerificationError('Original order status needs investigation')
        if captured_payment_id:
            capture = client.payment.fetch(captured_payment_id)
            items = [capture]
        else:
            collection = client.order.payments(payment.order_id)
            items = collection.get('items') if isinstance(collection, dict) else None
            if (not isinstance(items, list) or len(items) > 100
                    or type(collection.get('count')) is not int or collection['count'] != len(items)
                    or (type(order.get('attempts')) is int and order['attempts'] != len(items))):
                raise OriginalOrderVerificationError('Original order attempt history is incomplete or too large')
        captures = []
        statuses = []
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                    or item.get('order_id') != payment.order_id
                    or type(item.get('amount')) is not int or item['amount'] != expected
                    or item.get('currency') != 'INR'):
                raise OriginalOrderVerificationError('Original order payment evidence does not match')
            if captured_payment_id and item['id'] != captured_payment_id:
                raise OriginalOrderVerificationError('Original capture identity does not match')
            statuses.append(item.get('status'))
            if item.get('amount_refunded', 0) != 0 or item.get('refund_status'):
                raise OriginalOrderVerificationError('Original order refund requires operator investigation')
            if item.get('status') == 'captured':
                captures.append(item)
            elif item.get('status') not in {'failed', 'created', 'authorized', 'pending'}:
                raise OriginalOrderVerificationError('Original payment status requires investigation')
        if len(captures) > 1:
            raise OriginalOrderVerificationError('Multiple original captures require investigation')
        if order['status'] == 'paid' and paid == expected and due == 0 and len(captures) == 1:
            return {'status': 'paid_original', 'order_id': payment.order_id, 'captured_payment_id': captures[0]['id']}
        if paid != 0 or captures or order['status'] == 'paid' or captured_payment_id:
            raise OriginalOrderVerificationError('Partial or inconsistent original payment requires investigation')
        if not items or any(s != 'failed' for s in statuses):
            raise OriginalOrderVerificationError('An original payment is pending or authorized; no new collection')
        if payment.payment_id not in {item['id'] for item in items}:
            raise OriginalOrderVerificationError('Original failed payment is missing from provider history')
        return {'status': 'open', 'order_id': payment.order_id}
    except OriginalOrderVerificationError:
        raise
    except Exception:
        raise OriginalOrderVerificationError('Original order verification unavailable; no new collection') from None


def settle_original_under_claim(db, payment, evidence):
    """Stop local follow-up without inventing a successful recovery intervention."""
    import json
    from datetime import datetime
    from app.models.models import AuditLog, ReviewStatus
    row = bind_original_order(db, payment)
    if row is None or row.payment_id != payment.payment_id:
        return {'status': 'needs_reconciliation', 'reason': 'Original order ownership is ambiguous'}
    if row.captured_payment_id and row.captured_payment_id != evidence['captured_payment_id']:
        return {'status': 'needs_reconciliation', 'reason': 'Different original captures require investigation'}
    row.state = 'paid_original'
    row.captured_payment_id = evidence['captured_payment_id']
    row.resolved_at = row.resolved_at or datetime.utcnow()
    duplicate = payment.status in {'recovered', 'needs_reconciliation'}
    already = payment.status == 'paid_original'
    payment.status = 'needs_reconciliation' if duplicate else 'paid_original'
    db.query(Action).filter_by(payment_id=payment.payment_id, review_status=ReviewStatus.pending).update(
        {'review_status': ReviewStatus.expired, 'reason': 'Original order was paid; no recovery approval allowed'})
    if not already:
        db.add(AuditLog(payment_id=payment.payment_id,
                        event_type='duplicate_payment_detected' if duplicate else 'paid_original',
                        reason='Original order paid after a recovery capture; investigate possible duplicate collection' if duplicate
                        else 'Original order paid directly; excluded from recovered revenue',
                        payload_json=json.dumps(evidence)))
    db.commit()
    return {'status': 'needs_reconciliation' if duplicate else 'paid_original',
            'reason': 'Original order is paid; no further recovery collection'}


def verify_original_before_followup(db, payment):
    """Caller owns the payment claim. None means verified open, with no side effect."""
    if not payment.order_id:
        return None
    eligible, reason = original_order_eligibility(db, payment)
    row = db.get(OriginalOrderRecovery, payment.order_id)
    # A delayed original-capture event can persist the stop flag before claiming settlement.
    if not eligible and not (row.payment_id == payment.payment_id and row.state == 'paid_original'):
        return {'status': 'needs_reconciliation', 'reason': reason}
    try:
        evidence = read_original_order(payment)
    except OriginalOrderVerificationError as error:
        return {'status': 'needs_reconciliation', 'reason': str(error)}
    if evidence['status'] == 'paid_original':
        return settle_original_under_claim(db, payment, evidence)
    if row.state != 'active':
        return {'status': 'needs_reconciliation', 'reason': 'Original order stop flag requires investigation'}
    return None


def observe_original_capture(db, order_id, captured_payment_id):
    """Match known original orders only; recovery-resource matching has precedence."""
    from datetime import datetime
    from app.services.execution import _run_reserved
    from app.models.models import RecoveryReservation
    payment = db.query(Payment).filter_by(order_id=order_id).order_by(Payment.created_at, Payment.payment_id).first() if order_id else None
    if payment is None:
        return None
    row = bind_original_order(db, payment)
    if not row.payment_id:
        return {'status': 'needs_reconciliation', 'reason': 'Original order has ambiguous recovery history'}
    payment = db.get(Payment, row.payment_id)
    try:
        evidence = read_original_order(payment, captured_payment_id)
    except OriginalOrderVerificationError as error:
        return {'status': 'needs_reconciliation', 'reason': str(error)}
    if row.captured_payment_id and row.captured_payment_id != evidence['captured_payment_id']:
        return {'status': 'needs_reconciliation', 'reason': 'Conflicting original capture references require investigation'}
    # Persist a stop signal even while the case is busy. Never clear another owner's claim.
    row.state = 'paid_original'
    row.captured_payment_id = evidence['captured_payment_id']
    row.resolved_at = row.resolved_at or datetime.utcnow()
    db.commit()
    claim = db.get(RecoveryReservation, payment.payment_id)
    if claim and claim.state == 'needs_reconciliation':
        return {'status': 'needs_reconciliation', 'reason': 'Original order paid; existing uncertain recovery must be investigated'}
    waiting = claim.state if claim and claim.state in {'pending_review', 'awaiting_outcome'} else None
    return _run_reserved(db, payment.payment_id,
                         lambda: settle_original_under_claim(db, payment, evidence), expected_state=waiting)
