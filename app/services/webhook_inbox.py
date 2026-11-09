"""Keep verified correlation data, never contacts, card details or signatures."""

import json
import re
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.models.models import WebhookInbox, RecoveryIntent
from app.services.razorpay_client import client


MAX_REPLAY_ATTEMPTS = 20
REPLAYABLE_STATES = ("pending", "waiting_for_execution", "retryable")


class EventConflict(ValueError):
    pass


class EventNotReady(Exception):
    """No side effect has started; retry lookup after persistence/network recovers."""


def remember_verified_event(db, event_id, payload):
    entity = payload["payload"]["payment"]["entity"]
    description = entity.get("description")
    # Only a provider link reference is needed; arbitrary descriptions may be PII.
    if not isinstance(description, str) or not re.fullmatch(r"#[A-Za-z0-9_]{1,100}", description.strip()):
        description = None
    else:
        description = description.strip()
    minimal = {"event": payload["event"], "payload": {"payment": {"entity": {
        "id": entity["id"], "order_id": entity.get("order_id"), "description": description,
    }}}}
    encoded = json.dumps(minimal, sort_keys=True, separators=(",", ":"))
    row = db.get(WebhookInbox, event_id)
    if row is None:
        try:
            row = WebhookInbox(event_id=event_id, payload_json=encoded)
            db.add(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(WebhookInbox, event_id)
            if row is None:
                raise
    if row.payload_json != encoded:
        raise EventConflict("Event ID is already bound to different correlation data")
    return minimal


def mark_inbox_claimed(db, event_id):
    db.query(WebhookInbox).filter_by(event_id=event_id).update({
        "state": "processing", "attempts": WebhookInbox.attempts + 1,
    })
    db.commit()


def finish_inbox(db, event_id, state):
    row = db.get(WebhookInbox, event_id)
    if row is None:
        return state
    if state in REPLAYABLE_STATES and row.attempts >= MAX_REPLAY_ATTEMPTS:
        state = "needs_reconciliation"
    row.state = state
    row.available_at = datetime.utcnow() + timedelta(seconds=min(300, 15 * 2 ** min(row.attempts, 5)))
    return state


def unpersisted_recovery_intent(db, entity):
    """Read provider notes only when an external creation may still be in flight.

    Never turn an early failed recovery payment into a fresh recovery case.
    A lost creation response is deliberately not retried here.
    """
    candidates = db.query(RecoveryIntent).filter(RecoveryIntent.execution_id.is_(None), RecoveryIntent.state != 'cancelled_before_creation')
    order_id = entity.get("order_id")
    description = entity.get("description")
    resources = []
    if order_id:
        resources.append(("order", order_id, client.order.fetch))
    if description and description.startswith("#"):
        resources.append(("payment_link", "plink_" + description[1:], client.payment_link.fetch))
    for kind, resource_id, fetch in resources:
        pending = candidates.filter_by(provider_type=kind)
        known = pending.filter_by(provider_id=resource_id).first()
        if known:
            return known
        if pending.first() is None:
            continue
        try:
            resource = fetch(resource_id)
        except Exception as exc:
            raise EventNotReady("Provider resource lookup unavailable") from exc
        if not isinstance(resource, dict) or resource.get("id") != resource_id:
            raise EventNotReady("Provider resource lookup did not match requested ID")
        notes = resource.get("notes")
        intent_id = notes.get("recoverai_intent_id") if isinstance(notes, dict) else None
        if intent_id:
            if not isinstance(intent_id, str) or len(intent_id) > 128:
                raise EventNotReady("Invalid provider correlation reference")
            intent = db.get(RecoveryIntent, intent_id)
            if intent is None or intent.provider_type != kind:
                raise EventNotReady("Provider reference requires reconciliation")
            return intent
    return None
