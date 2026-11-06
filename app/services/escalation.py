"""Expire human reviews under the same case lock used by approvals.

Timeouts never authorize or retry an external action. Review, case state,
claim cleanup and audit are committed in one database transaction.
"""

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.models.models import (Action, DecisionType, ReviewStatus, AuditLog,
                               Payment, RecoveryReservation)


def expire_review_under_claim(db, action, now=None):
    """Caller must own the case claim. No commit and no external provider calls."""
    now = now or datetime.utcnow()
    if (action is None or action.decision_type != DecisionType.human_review
            or action.review_status != ReviewStatus.pending or action.review_deadline is None
            or action.review_deadline > now):
        return False, True
    action.review_status = ReviewStatus.expired
    other_pending = db.query(Action).filter(
        Action.payment_id == action.payment_id, Action.id != action.id,
        Action.decision_type == DecisionType.human_review, Action.review_status == ReviewStatus.pending,
    ).first() is not None
    payment = db.get(Payment, action.payment_id)
    if (not other_pending and payment is not None and payment.status == 'failed'
            and (payment.razorpay_state or '').lower() not in {'captured', 'authorized'}):
        payment.status = 'closed_unrecovered'
    db.add(AuditLog(payment_id=action.payment_id, timestamp=now,
        event_type='human_review_expired',
        reason=f'deadline {action.review_deadline} passed with no human action - no risky action auto-executed',
        payload_json=json.dumps({'action_id': action.id, 'deadline': action.review_deadline.isoformat()})))
    return True, other_pending


def _claim_for_expiry(db, payment_id):
    owner = uuid4().hex
    changed = db.query(RecoveryReservation).filter_by(payment_id=payment_id, state='pending_review').update(
        {'owner': owner, 'state': 'processing', 'updated_at': datetime.utcnow()})
    if changed:
        return owner
    try:
        # Also handles legacy reviews that predate reservation rows. A savepoint
        # prevents a duplicate claim from rolling back unrelated caller state.
        with db.begin_nested():
            db.add(RecoveryReservation(payment_id=payment_id, owner=owner, state='processing'))
            db.flush()
        return owner
    except IntegrityError:
        return None


def expire_overdue_reviews(db, limit=100, now=None) -> list:
    if not 1 <= limit <= 1000:
        raise ValueError('Review expiry limit must be between 1 and 1000')
    now = now or datetime.utcnow()
    candidates = db.query(Action.id, Action.payment_id).outerjoin(
        RecoveryReservation, RecoveryReservation.payment_id == Action.payment_id,
    ).filter(Action.decision_type == DecisionType.human_review,
        Action.review_status == ReviewStatus.pending, Action.review_deadline <= now,
        or_(RecoveryReservation.payment_id.is_(None), RecoveryReservation.state == 'pending_review'),
    ).order_by(Action.review_deadline, Action.id).limit(limit).all()
    expired = []
    for action_id, payment_id in candidates:
        try:
            owner = _claim_for_expiry(db, payment_id)
            if owner is None:
                db.rollback()
                continue
            db.expire_all()
            action = db.get(Action, action_id)
            changed, other_pending = expire_review_under_claim(db, action, now)
            if not changed:
                db.rollback()
                continue
            claim = db.query(RecoveryReservation).filter_by(payment_id=payment_id, owner=owner)
            if other_pending:
                claim.update({'state': 'pending_review', 'updated_at': now})
            else:
                claim.delete()
            db.commit()
            expired.append(action)
        except Exception:
            db.rollback()
            raise
    return expired
