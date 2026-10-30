"""Durable claims: database uniqueness, rather than a check-then-act race."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.models.models import RecoveryReservation, WebhookReceipt


class RecoveryInProgress(Exception):
    """No operation was started because another request owns the payment."""


def reserve_webhook(db, event_id):
    """Return None only for the request that committed the new claim."""
    changed = db.query(WebhookReceipt).filter_by(event_id=event_id, state="retryable").update(
        {"state": "processing"},
    )
    db.commit()
    if changed:
        return None
    try:
        db.add(WebhookReceipt(event_id=event_id, state="processing"))
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        existing = db.get(WebhookReceipt, event_id)
        if existing is None:
            raise
        return existing.state


def finish_webhook(db, event_id, state):
    db.query(WebhookReceipt).filter_by(event_id=event_id).update({"state": state})
    db.commit()


def reserve_recovery(db, payment_id, expected_state=None):
    """Insert a claim, or atomically take over an expected waiting phase.

    Processing/reconciliation claims never expire automatically: a lost HTTP
    response can mean the provider already created the order or payment link.
    """
    owner = uuid4().hex
    if expected_state is not None:
        changed = db.query(RecoveryReservation).filter_by(
            payment_id=payment_id, state=expected_state,
        ).update({"owner": owner, "state": "processing", "updated_at": datetime.utcnow()})
        db.commit()
        if changed:
            return owner
    try:
        db.add(RecoveryReservation(payment_id=payment_id, owner=owner, state="processing"))
        db.commit()
        return owner
    except IntegrityError:
        db.rollback()
        if db.get(RecoveryReservation, payment_id) is None:
            raise
        return None


def finish_recovery(db, payment_id, owner, state=None):
    claim = db.query(RecoveryReservation).filter_by(payment_id=payment_id, owner=owner)
    if state is None:
        claim.delete()
    else:
        claim.update({"state": state, "updated_at": datetime.utcnow()})
    db.commit()
