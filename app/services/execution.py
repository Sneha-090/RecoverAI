"""
Execution service - Section 21 of spec.
Executes the chosen action, and observe_outcome() closes the loop:
check real result -> if failed, re-score (tried action auto-excluded
by decide()) and execute the next best action -> repeat until
recovered or no candidates remain.
"""

import json
from datetime import datetime, timedelta

from app.config import settings
from app.services.decision import decide
from app.services.eligibility import is_retry_eligible
from app.services.order_service import create_test_order, create_payment_link
from app.services.razorpay_client import client
from app.models.models import Action, AuditLog, DecisionType, ReviewStatus, Payment


def _log_audit(db, payment_id, event_type, reason, payload=None):
    entry = AuditLog(
        payment_id=payment_id,
        timestamp=datetime.utcnow(),
        event_type=event_type,
        reason=reason,
        payload_json=json.dumps(payload) if payload else None,
    )
    db.add(entry)
    db.commit()


def execute_action(db, payment) -> dict:
    decision = decide(db, payment)

    if decision["decision_type"] == "skip":
        _log_audit(db, payment.payment_id, "skipped", decision["reason"])
        return {**decision, "executed": False}

    if decision["decision_type"] == "human_review":
        deadline = datetime.utcnow() + timedelta(hours=settings.human_review_timeout_hours)
        action_row = Action(
            payment_id=payment.payment_id,
            action_type=decision["chosen_action"],
            chosen_at=datetime.utcnow(),
            decision_type=DecisionType.human_review,
            reason=decision["reason"],  # Module A
            escalated_at=datetime.utcnow(),
            review_deadline=deadline,
            review_status=ReviewStatus.pending,
        )
        db.add(action_row)
        db.commit()
        _log_audit(db, payment.payment_id, "escalated", decision["reason"], payload={"review_deadline": deadline.isoformat()})
        return {**decision, "executed": False, "review_deadline": deadline.isoformat()}

    action_type = decision["chosen_action"]

    if action_type == "retry":
        eligible, reason = is_retry_eligible(db, payment)
        if not eligible:
            _log_audit(db, payment.payment_id, "retry_blocked", reason)
            return {
                "chosen_action": None,
                "decision_type": "skip",
                "reason": f"eligibility changed before execution: {reason}",
                "executed": False,
            }

    if action_type == "retry":
        result = create_test_order(payment.amount, receipt=f"retry_{payment.payment_id}_{datetime.utcnow().timestamp():.0f}")
        payload = {"type": "order", "order_id": result["id"]}
    else:  # payment_link or alt_method
        desc = "RecoverAI recovery link" if action_type == "payment_link" else "RecoverAI: try an alternate payment method"
        result = create_payment_link(payment.amount, description=desc)
        payload = {"type": "payment_link", "payment_link_id": result["id"], "short_url": result.get("short_url")}

    action_row = Action(
        payment_id=payment.payment_id,
        action_type=action_type,
        chosen_at=datetime.utcnow(),
        decision_type=DecisionType.auto,
        reason=decision["reason"],  # Module A
    )
    db.add(action_row)
    db.commit()

    _log_audit(db, payment.payment_id, "executed", decision["reason"], payload=payload)

    return {**decision, "executed": True, "razorpay_payload": payload}


def _get_last_execution_payload(db, payment_id: str):
    entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.payment_id == payment_id,
            AuditLog.event_type.in_(
                ["executed", "human_approved_executed"]
            ),
        )
        .order_by(
            AuditLog.timestamp.desc(),
            AuditLog.id.desc(),
        )
        .first()
    )

    if not entry or not entry.payload_json:
        return None

    try:
        return json.loads(entry.payload_json)
    except (TypeError, json.JSONDecodeError):
        return None


def _check_real_outcome(payload: dict) -> str:
    """Returns 'success' or 'failed' by checking real Razorpay state."""
    if payload["type"] == "order":
        payments = client.order.payments(payload["order_id"])
        items = payments.get("items", [])
        if any(p.get("status") == "captured" for p in items):
            return "success"
        return "failed"

    if payload["type"] == "payment_link":
        link = client.payment_link.fetch(payload["payment_link_id"])
        if link.get("status") == "paid":
            return "success"
        return "failed"

    return "failed"


def observe_outcome(db, payment) -> dict:
    payload = _get_last_execution_payload(db, payment.payment_id)
    if not payload:
        return {"status": "no_prior_execution", "reason": "no executed action found to observe"}

    last_action = (
        db.query(Action)
        .filter(Action.payment_id == payment.payment_id, Action.decision_type == "auto")
        .order_by(Action.chosen_at.desc())
        .first()
    )

    result = _check_real_outcome(payload)

    from app.models.models import Outcome
    outcome_row = Outcome(
        payment_id=payment.payment_id,
        action_type=last_action.action_type,
        observed_result=result,
        observed_at=datetime.utcnow(),
    )
    db.add(outcome_row)

    if result == "success":
        payment.status = "recovered"
        db.commit()
        _log_audit(db, payment.payment_id, "recovered", f"{last_action.action_type} succeeded")
        return {"status": "recovered", "action_type": last_action.action_type}

    db.commit()
    _log_audit(db, payment.payment_id, "attempt_failed", f"{last_action.action_type} did not recover the payment")

    next_decision = execute_action(db, payment)

    if next_decision["decision_type"] == "skip":
        payment.status = "closed_unrecovered"
        db.commit()
        _log_audit(db, payment.payment_id, "closed_unrecovered", next_decision["reason"])
        return {"status": "closed_unrecovered", "reason": next_decision["reason"]}

    if next_decision["decision_type"] == "human_review":
        return {
            "status": "escalated_to_human_review",
            "next": next_decision,
            "review_deadline": next_decision.get("review_deadline"),
        }

    return {"status": "next_action_attempted", "next": next_decision}
def human_review_action(db, payment_id: str, chosen_action: str) -> dict:
    """
    Business-user-driven approval: takes the human's chosen action
    (which may or may not match the ML's original recommendation) for
    a pending human_review case, re-verifies eligibility if it's a
    retry, executes it for real, and marks the review as actioned.
    """
    action_row = (
        db.query(Action)
        .filter(
            Action.payment_id == payment_id,
            Action.decision_type == DecisionType.human_review,
            Action.review_status == ReviewStatus.pending,
        )
        .first()
    )
    if not action_row:
        return {"success": False, "reason": "No pending human_review case found for this payment."}

    payment = db.query(__import__("app.models.models", fromlist=["Payment"]).Payment).filter_by(payment_id=payment_id).first()

    if chosen_action == "retry":
        eligible, reason = is_retry_eligible(db, payment)
        if not eligible:
            return {"success": False, "reason": f"Retry not eligible: {reason}"}
        result = create_test_order(payment.amount, receipt=f"human_{payment_id}_{datetime.utcnow().timestamp():.0f}")
        payload = {"type": "order", "order_id": result["id"]}
    else:
        desc = "RecoverAI recovery link (human-approved)" if chosen_action == "payment_link" else "RecoverAI: alternate method (human-approved)"
        result = create_payment_link(payment.amount, description=desc)
        payload = {"type": "payment_link", "payment_link_id": result["id"], "short_url": result.get("short_url")}

    new_action = Action(
        payment_id=payment_id,
        action_type=chosen_action,
        chosen_at=datetime.utcnow(),
        decision_type=DecisionType.auto,
        reason=f"human-approved action (original ML recommendation: {action_row.action_type})",
    )
    db.add(new_action)

    action_row.review_status = ReviewStatus.actioned
    db.commit()

    _log_audit(db, payment_id, "human_approved_executed", f"Business user chose {chosen_action}", payload=payload)

    return {"success": True, "executed_action": chosen_action, "razorpay_payload": payload}