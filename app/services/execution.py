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
from app.services.eligibility import is_recovery_eligible, is_retry_eligible
from app.services.order_service import create_test_order, create_payment_link
from app.services.razorpay_client import client
from app.models.models import (Action, AuditLog, DecisionType, ReviewStatus, Payment,
                               Outcome, ExecutionOutcome, RecoveryReservation)
from app.services.reservations import reserve_recovery, finish_recovery, RecoveryInProgress
from app.services.execution_records import record_execution, resolve_execution


def _run_reserved(db, payment_id, operation, expected_state=None):
    owner = reserve_recovery(db, payment_id, expected_state)
    if owner is None:
        raise RecoveryInProgress("An active recovery operation already exists for this payment")
    try:
        result = operation()
        state = None
        if result.get("executed") or result.get("success") or result.get("status") == "next_action_attempted":
            state = "awaiting_outcome"
        elif result.get("decision_type") == "human_review" or result.get("status") == "escalated_to_human_review":
            state = "pending_review"
        elif result.get("status") == "awaiting_outcome":
            state = "awaiting_outcome"
        elif result.get("status") == "pending_review":
            state = "pending_review"
        elif result.get("status") == "needs_reconciliation":
            state = "needs_reconciliation"
        finish_recovery(db, payment_id, owner, state)
        return result
    except Exception:
        db.rollback()
        finish_recovery(db, payment_id, owner, "needs_reconciliation")
        raise


def _busy_result():
    return {
        "chosen_action": None, "decision_type": "pending",
        "reason": "An active recovery action already exists; no new action created",
        "executed": False, "status": "already_processing",
    }


def _log_audit(db, payment_id, event_type, reason, payload=None, action=None):
    entry = AuditLog(
        payment_id=payment_id,
        timestamp=datetime.utcnow(),
        event_type=event_type,
        reason=reason,
        payload_json=json.dumps(payload) if payload else None,
    )
    db.add(entry)
    if action is not None:
        db.flush()
        record_execution(db, db.get(Payment, payment_id), action, entry, payload)
    db.commit()


def execute_action(db, payment) -> dict:
    try:
        return _run_reserved(db, payment.payment_id, lambda: _execute_action(db, payment))
    except RecoveryInProgress:
        return _busy_result()


def _execute_action(db, payment) -> dict:
    db.refresh(payment)
    # Also recognize work created before reservation tables were installed.
    pending = db.query(Action).filter_by(
        payment_id=payment.payment_id, decision_type=DecisionType.human_review,
        review_status=ReviewStatus.pending,
    ).first()
    if pending:
        return {**_busy_result(), "status": "pending_review"}
    unfinished = db.query(Action).outerjoin(
        Outcome,
        (Outcome.payment_id == Action.payment_id) & (Outcome.action_type == Action.action_type),
    ).filter(
        Action.payment_id == payment.payment_id, Action.decision_type == DecisionType.auto,
        Outcome.id.is_(None),
    ).first()
    if unfinished:
        return {**_busy_result(), "status": "awaiting_outcome"}
    decision = decide(db, payment)

    if decision["decision_type"] == "skip":
        _log_audit(db, payment.payment_id, "skipped", decision["reason"])
        return {**decision, "executed": False}

    # Recheck before execution/escalation in case the case changed during scoring.
    eligible, reason = is_recovery_eligible(payment)
    if not eligible:
        _log_audit(db, payment.payment_id, "skipped", reason)
        return {
            "chosen_action": None, "decision_type": "skip",
            "reason": reason, "executed": False,
        }

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

    _log_audit(db, payment.payment_id, "executed", decision["reason"], payload=payload, action=action_row)

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
    """Unpaid/open attempts remain pending rather than starting another action."""
    if payload["type"] == "order":
        payments = client.order.payments(payload["order_id"])
        items = payments.get("items", [])
        captured = [p for p in items if p.get("status") == "captured"]
        if captured:
            if not any(_verified_amount(p, payload) for p in captured):
                raise ValueError("Captured recovery amount or currency does not match execution")
            return "success"
        return "failed" if items and all(p.get("status") == "failed" for p in items) else "pending"

    if payload["type"] == "payment_link":
        link = client.payment_link.fetch(payload["payment_link_id"])
        if link.get("status") == "paid":
            if (link.get("id") != payload["payment_link_id"]
                    or not _verified_amount(link, payload)
                    or link.get("amount_paid") != payload["expected_amount_paise"]):
                raise ValueError("Paid recovery link does not match execution amount or currency")
            return "success"
        return "failed" if link.get("status") in {"cancelled", "expired"} else "pending"

    raise ValueError("Unknown recovery payload type")


def _verified_amount(resource, payload):
    return (resource.get("amount") == payload["expected_amount_paise"]
            and resource.get("currency") == payload["expected_currency"])


def observe_outcome(db, payment, expected_order_id=None, expected_payment_link_id=None) -> dict:
    claim = db.get(RecoveryReservation, payment.payment_id)
    waiting_state = claim.state if claim and claim.state in {"pending_review", "awaiting_outcome"} else "awaiting_outcome"
    if claim is None and db.query(Action).filter_by(
        payment_id=payment.payment_id, review_status=ReviewStatus.pending,
    ).first():
        waiting_state = "pending_review"
    return _run_reserved(
        db, payment.payment_id,
        lambda: _observe_outcome(db, payment, expected_order_id, expected_payment_link_id, waiting_state),
        waiting_state,
    )


def _observe_outcome(db, payment, expected_order_id=None, expected_payment_link_id=None, waiting_state="awaiting_outcome") -> dict:
    db.refresh(payment)
    if payment.status == "recovered":
        return {"status": "recovered"}
    latest = _get_last_execution_payload(db, payment.payment_id)
    if latest is None:
        return {"status": "no_prior_execution", "reason": "No executed action found to observe"}
    execution, payload = resolve_execution(
        db, payment, expected_order_id, expected_payment_link_id,
    )
    if not execution:
        if payload:
            return {"status": "needs_reconciliation", "reason": "Execution history cannot be attributed unambiguously"}
        return {"status": waiting_state, "reason": "No matching recovery execution found"}
    action = db.get(Action, execution.action_id)
    historical = latest != payload
    payload = {**payload, "expected_amount_paise": execution.amount_paise,
               "expected_currency": execution.currency}

    result = _check_real_outcome(payload)
    if result == "pending":
        return {"status": waiting_state, "reason": "Provider has not reported a terminal outcome"}

    attribution = db.get(ExecutionOutcome, execution.id)
    already_observed = attribution is not None
    outcome_row = db.get(Outcome, attribution.outcome_id) if attribution else None
    if outcome_row is None:
        # Adopt an old result only if its action and time interval identify it.
        next_action = db.query(Action).filter(
            Action.payment_id == payment.payment_id, Action.decision_type == "auto",
            Action.chosen_at > action.chosen_at,
        ).order_by(Action.chosen_at, Action.id).first()
        candidates = db.query(Outcome).outerjoin(
            ExecutionOutcome, ExecutionOutcome.outcome_id == Outcome.id,
        ).filter(Outcome.payment_id == payment.payment_id,
                 Outcome.action_type == action.action_type,
                 Outcome.observed_at >= action.chosen_at,
                 ExecutionOutcome.execution_id.is_(None))
        if next_action:
            candidates = candidates.filter(Outcome.observed_at <= next_action.chosen_at)
        prior = candidates.all()
        same_kind_count = db.query(Action).filter_by(
            payment_id=payment.payment_id, action_type=action.action_type, decision_type=DecisionType.auto,
        ).count() if prior else 0
        if len(prior) > 1 or (prior and same_kind_count != 1):
            return {"status": "needs_reconciliation", "reason": "Ambiguous legacy outcomes"}
        outcome_row = prior[0] if prior else Outcome(
            payment_id=payment.payment_id, action_type=action.action_type,
            observed_result=result, observed_at=datetime.utcnow(),
        )
        already_observed = bool(prior)
        db.add(outcome_row)
        db.flush()
        db.add(ExecutionOutcome(execution_id=execution.id, outcome_id=outcome_row.id))
    if outcome_row.observed_result == "success":
        result = "success"
    if result == "success":
        outcome_row.observed_result = "success"
        outcome_row.observed_at = datetime.utcnow()

    if result == "success":
        payment.status = "recovered"
        # A late capture settles the case even if a newer review was waiting.
        db.query(Action).filter_by(
            payment_id=payment.payment_id, review_status=ReviewStatus.pending,
        ).update({"review_status": ReviewStatus.expired, "reason": "Case recovered by an earlier execution"})
        db.commit()
        _log_audit(db, payment.payment_id, "recovered", f"{action.action_type} succeeded",
                   payload={"execution_id": execution.id, "provider_id": execution.provider_id})
        return {"status": "recovered", "action_type": action.action_type, "execution_id": execution.id}

    db.commit()
    if historical or already_observed or waiting_state == "pending_review":
        return {"status": "historical_outcome_observed" if payment.status == "closed_unrecovered" else waiting_state,
                "reason": "Historical or already observed failure; no new action started"}
    _log_audit(db, payment.payment_id, "attempt_failed", f"{action.action_type} did not recover the payment",
               payload={"execution_id": execution.id})

    # Keep ownership while advancing to the next action.
    next_decision = _execute_action(db, payment)

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
    try:
        return _run_reserved(
            db, payment_id, lambda: _human_review_action(db, payment_id, chosen_action), "pending_review",
        )
    except RecoveryInProgress as exc:
        return {"success": False, "reason": str(exc)}


def _human_review_action(db, payment_id: str, chosen_action: str) -> dict:
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

    if chosen_action not in {"retry", "payment_link", "alt_method"}:
        return {"success": False, "status": "pending_review", "reason": "Unknown recovery action."}
    if action_row.review_deadline and action_row.review_deadline <= datetime.utcnow():
        action_row.review_status = ReviewStatus.expired
        db.commit()
        return {"success": False, "reason": "Human review deadline has passed."}

    payment = db.query(Payment).filter_by(payment_id=payment_id).first()
    if payment is None:
        return {"success": False, "reason": "Payment not found."}

    eligible, reason = is_recovery_eligible(payment)
    if not eligible:
        _log_audit(db, payment_id, "human_review_blocked", reason)
        return {"success": False, "status": "pending_review", "reason": reason}

    if chosen_action == "retry":
        eligible, reason = is_retry_eligible(db, payment)
        if not eligible:
            return {"success": False, "status": "pending_review", "reason": f"Retry not eligible: {reason}"}
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

    _log_audit(db, payment_id, "human_approved_executed", f"Business user chose {chosen_action}", payload=payload, action=new_action)

    return {"success": True, "executed_action": chosen_action, "razorpay_payload": payload}
