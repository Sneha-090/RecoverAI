"""Indexed provider correlation; legacy audit records are imported conservatively."""

import json
from decimal import Decimal

from app.models.models import Action, AuditLog, RecoveryExecution


def amount_paise(amount):
    return int(Decimal(str(amount)) * 100)


def record_execution(db, payment, action, audit, payload):
    kind = payload["type"]
    provider_id = payload["order_id" if kind == "order" else "payment_link_id"]
    row = RecoveryExecution(
        payment_id=payment.payment_id, action_id=action.id, audit_id=audit.id,
        provider_type=kind, provider_id=provider_id,
        amount_paise=amount_paise(payment.amount), currency="INR",
    )
    db.add(row)
    db.flush()
    return row


def resolve_execution(db, payment, order_id=None, payment_link_id=None):
    """Resolve the exact resource, or the latest execution for manual observation.

    Legacy executions are bound only when exactly one executed action exists
    between consecutive audit timestamps. Ambiguous history needs reconciliation.
    """
    entries = db.query(AuditLog).filter(
        AuditLog.payment_id == payment.payment_id,
        AuditLog.event_type.in_(["executed", "human_approved_executed"]),
    ).order_by(AuditLog.timestamp, AuditLog.id).all()
    previous_time = None
    selected = None
    for audit in entries:
        try:
            payload = json.loads(audit.payload_json or "{}")
        except (TypeError, json.JSONDecodeError):
            previous_time = audit.timestamp
            continue
        matches = (
            (order_id and payload.get("type") == "order" and payload.get("order_id") == order_id)
            or (payment_link_id and payload.get("type") == "payment_link"
                and payload.get("payment_link_id") == payment_link_id)
            or (not order_id and not payment_link_id)
        )
        if matches:
            selected = (audit, payload, previous_time)
        previous_time = audit.timestamp
    if selected is None:
        return None, None
    audit, payload, previous_time = selected
    row = db.query(RecoveryExecution).filter_by(audit_id=audit.id).first()
    if row:
        return row, payload
    actions = db.query(Action).filter(
        Action.payment_id == payment.payment_id, Action.decision_type == "auto",
        Action.chosen_at <= audit.timestamp,
    )
    if previous_time is not None:
        actions = actions.filter(Action.chosen_at > previous_time)
    candidates = actions.all()
    if len(candidates) != 1 or payload.get("type") not in {"order", "payment_link"}:
        return None, payload
    key = "order_id" if payload["type"] == "order" else "payment_link_id"
    if not payload.get(key):
        return None, payload
    return record_execution(db, payment, candidates[0], audit, payload), payload
