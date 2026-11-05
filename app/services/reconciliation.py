"""Reviewed reconciliation: provider reads only; never create or retry a charge."""

from datetime import datetime
from uuid import uuid4
import json
import re

from app.models.models import (Action, AuditLog, DecisionType, Payment, RecoveryExecution,
                               RecoveryIntent, RecoveryReservation)
from app.services.execution import _observe_outcome
from app.services.execution_records import amount_paise, record_execution
from app.services.razorpay_client import client
from app.services.reservations import finish_recovery


class ReconciliationError(ValueError):
    pass


def list_stuck_cases(db, limit=50):
    return [{"payment_id": claim.payment_id, "state": claim.state,
             "updated_at": claim.updated_at.isoformat(), "amount": payment.amount}
            for claim, payment in db.query(RecoveryReservation, Payment).join(
                Payment, Payment.payment_id == RecoveryReservation.payment_id).filter(
                RecoveryReservation.state.in_(["processing", "needs_reconciliation"])
            ).order_by(RecoveryReservation.updated_at, RecoveryReservation.payment_id).limit(limit).all()]


def reconciliation_references(db, payment_id):
    references = []
    for row in db.query(RecoveryExecution).filter_by(payment_id=payment_id).order_by(RecoveryExecution.id).all():
        references.append({"key": f"execution:{row.id}", "kind": row.provider_type,
                           "provider_id": row.provider_id, "amount_paise": row.amount_paise})
    for row in db.query(RecoveryIntent).filter_by(payment_id=payment_id, execution_id=None).order_by(RecoveryIntent.created_at).all():
        references.append({"key": f"intent:{row.id}", "kind": row.provider_type,
                           "provider_id": row.provider_id, "amount_paise": None})
    return references


def _reference(db, payment_id, reference_key, supplied_provider_id=None):
    payment = db.get(Payment, payment_id)
    if payment is None or not isinstance(reference_key, str):
        raise ReconciliationError("Payment or reference not found.")
    prefix, _, identity = reference_key.partition(":")
    if prefix == "execution" and identity.isdigit():
        reference = db.get(RecoveryExecution, int(identity))
    elif prefix == "intent":
        reference = db.get(RecoveryIntent, identity)
    else:
        raise ReconciliationError("Unknown recovery reference.")
    if reference is None or reference.payment_id != payment_id:
        raise ReconciliationError("Reference does not belong to this case.")
    if isinstance(reference, RecoveryIntent) and reference.execution_id is not None:
        execution = db.get(RecoveryExecution, reference.execution_id)
        if execution is None or execution.payment_id != payment_id:
            raise ReconciliationError("Execution binding needs manual investigation.")
        reference = execution
    resource_id = reference.provider_id or supplied_provider_id
    if supplied_provider_id and reference.provider_id and supplied_provider_id != reference.provider_id:
        raise ReconciliationError("The stored provider reference cannot be replaced.")
    provider_type = reference.provider_type
    pattern = r"order_[A-Za-z0-9_]{1,100}" if provider_type == "order" else r"plink_[A-Za-z0-9_]{1,100}"
    if not isinstance(resource_id, str) or not re.fullmatch(pattern, resource_id):
        raise ReconciliationError("Enter the matching Razorpay order or payment link ID.")
    return payment, reference, resource_id


def check_reconciliation_status(db, payment_id, reference_key, supplied_provider_id=None):
    """No database writes. Evidence is displayed to the operator, never trusted on apply."""
    payment, reference, resource_id = _reference(db, payment_id, reference_key, supplied_provider_id)
    kind = reference.provider_type
    expected_amount = reference.amount_paise if isinstance(reference, RecoveryExecution) else amount_paise(payment.amount)
    currency = reference.currency if isinstance(reference, RecoveryExecution) else "INR"
    resource = client.order.fetch(resource_id) if kind == "order" else client.payment_link.fetch(resource_id)
    if (not isinstance(resource, dict) or resource.get("id") != resource_id
            or resource.get("amount") != expected_amount or resource.get("currency") != currency):
        raise ReconciliationError("Provider ID, amount or currency does not match this case.")
    if isinstance(reference, RecoveryIntent):
        notes = resource.get("notes")
        if not isinstance(notes, dict) or notes.get("recoverai_intent_id") != reference.id:
            raise ReconciliationError("Provider reference is not verified for this recovery intent.")
    if kind == "order":
        items = client.order.payments(resource_id).get("items", [])
        captured = [item for item in items if item.get("status") == "captured"]
        if captured and not any(item.get("amount") == expected_amount and item.get("currency") == currency
                                and item.get("order_id") == resource_id for item in captured):
            raise ReconciliationError("Captured payment does not match the recovery order.")
        result = "success" if captured else "failed" if items and all(item.get("status") == "failed" for item in items) else "pending"
    else:
        if resource.get("status") == "paid" and resource.get("amount_paid") != expected_amount:
            raise ReconciliationError("The recovery link has not been paid in full.")
        result = "success" if resource.get("status") == "paid" else "failed" if resource.get("status") in {"expired", "cancelled"} else "pending"
    return {"result": result, "provider_status": resource.get("status", "unknown"),
            "provider_id": resource_id, "provider_type": kind, "amount_paise": expected_amount,
            "currency": currency, "checked_at": datetime.utcnow().isoformat() + "Z"}


def _bind_verified_intent(db, payment, intent, provider_id):
    # A DB failure can occur before OR after the executed Action was saved.
    actions = db.query(Action).filter(Action.payment_id == payment.payment_id,
        Action.decision_type == DecisionType.auto, Action.chosen_at >= intent.created_at).all()
    if len(actions) > 1 or (actions and actions[0].action_type != intent.action_type):
        raise ReconciliationError("Ambiguous action history needs manual investigation.")
    action = actions[0] if actions else Action(payment_id=payment.payment_id,
        action_type=intent.action_type, decision_type=DecisionType.auto,
        chosen_at=intent.created_at, reason="Existing provider resource verified during reconciliation")
    if action.id and db.query(RecoveryExecution).filter_by(action_id=action.id).first():
        raise ReconciliationError("Action is already bound to another provider resource.")
    db.add(action)
    db.flush()
    payload = {"type": intent.provider_type,
               "order_id" if intent.provider_type == "order" else "payment_link_id": provider_id}
    audit = AuditLog(payment_id=payment.payment_id, event_type="executed",
                     reason="Bound existing provider resource after operator verification",
                     payload_json=json.dumps(payload))
    db.add(audit)
    db.flush()
    execution = record_execution(db, payment, action, audit, payload)
    intent.provider_id, intent.execution_id, intent.state = provider_id, execution.id, "bound"
    return execution


def reconcile_verified_success(db, payment_id, reference_key, operator_username, supplied_provider_id=None):
    """Re-check evidence under an exclusive claim. Only a verified success settles.

    Never take over a processing claim, expire a claim, replay an uncertain
    webhook, or call an external create/cancel endpoint.
    """
    if not isinstance(operator_username, str) or not operator_username.strip() or len(operator_username) > 64:
        return {"status": "blocked", "reason": "An authenticated operator is required."}
    owner = uuid4().hex
    changed = db.query(RecoveryReservation).filter_by(payment_id=payment_id, state="needs_reconciliation").update(
        {"owner": owner, "state": "processing", "updated_at": datetime.utcnow()})
    db.commit()
    if not changed:
        return {"status": "blocked", "reason": "Case is active, already settled, or no longer awaiting reconciliation."}
    state = "needs_reconciliation"
    try:
        db.expire_all()
        evidence = check_reconciliation_status(db, payment_id, reference_key, supplied_provider_id)
        if evidence["result"] != "success":
            return {"status": "not_settled", "reason": "Provider has not verified full recovery. The case remains blocked."}
        payment, reference, provider_id = _reference(db, payment_id, reference_key, supplied_provider_id)
        execution = _bind_verified_intent(db, payment, reference, provider_id) if isinstance(reference, RecoveryIntent) else reference
        correlation = {"expected_order_id" if execution.provider_type == "order" else "expected_payment_link_id": provider_id}
        result = _observe_outcome(db, payment, **correlation, settle_only=True)
        if result["status"] != "recovered":
            db.rollback()
            return {"status": "not_settled", "reason": "Outcome requires manual investigation. The case remains blocked."}
        db.add(AuditLog(payment_id=payment_id, event_type="reconciliation_settled",
                        reason="Operator settled a verified provider success",
                        payload_json=json.dumps({"operator": operator_username, "execution_id": execution.id,
                                                 "provider_id": provider_id})))
        db.commit()
        state = None
        return {"status": "recovered", "execution_id": execution.id}
    except ReconciliationError as exc:
        db.rollback()
        return {"status": "not_settled", "reason": str(exc)}
    except Exception:
        db.rollback()
        return {"status": "not_settled", "reason": "Verification could not complete. The case remains blocked; no new payment action was requested."}
    finally:
        finish_recovery(db, payment_id, owner, state)
