"""
Rule-based error_code -> root-cause mapping.
Deterministic lookup only - no ML, no learned weights (Section 7 of spec).

Cause categories are kept intentionally small and mapped to the three
candidate actions (Section 8) so Day 3's ML features and Day 4's action
eligibility can consume `cause` directly.
"""

from datetime import datetime
from sqlalchemy.orm import Session

from app.models.models import Payment, Diagnosis

# error_code -> cause. Based on Razorpay's documented error codes/reasons.
# https://razorpay.com/docs/errors/
ERROR_CODE_CAUSE_MAP = {
    # Card issues
    "GATEWAY_ERROR": "bank_declined",
    "BAD_REQUEST_ERROR": "bank_declined",       # generic decline bucket (Day 1's real case)
    "SERVER_ERROR": "network_error",

    # error_reason-level refinement (used when error_code is generic
    # but Razorpay gives a more specific reason string)
}

ERROR_REASON_CAUSE_MAP = {
    "payment_failed": "bank_declined",
    "insufficient_funds": "insufficient_funds",
    "card_declined": "card_declined",
    "expired_card": "expired_card",
    "invalid_card": "invalid_card",
    "authentication_failed": "authentication_failed",
    "processing_error": "network_error",
    "issuer_unavailable": "network_error",
    "payment_cancelled": "customer_cancelled",
}

FALLBACK_CAUSE = "unclassified_error"


def diagnose(payment: Payment) -> str:
    """
    Pure function: given a Payment row, return a cause string.
    Never returns None - falls back to FALLBACK_CAUSE if nothing matches,
    per Day 2 DoD (100% of ingested payments get a cause, no nulls).
    """
    reason = (payment.razorpay_error_code or "").strip()
    error_reason  = getattr(payment, "razorpay_error_reason", None)
     # not on model yet - see note below

    # Prefer the more specific error_reason if we have one, else fall back
    # to error_code, else fall back to the safe default.
    if error_reason and error_reason in ERROR_REASON_CAUSE_MAP:
        return ERROR_REASON_CAUSE_MAP[error_reason]

    if reason in ERROR_CODE_CAUSE_MAP:
        return ERROR_CODE_CAUSE_MAP[reason]

    return FALLBACK_CAUSE


def diagnose_and_store(db: Session, payment: Payment) -> Diagnosis:
    """
    Runs diagnose() and writes a Diagnosis row. Idempotent per payment:
    if a diagnosis already exists for this payment, it's updated, not duplicated.
    """
    cause = diagnose(payment)

    existing = (
        db.query(Diagnosis)
        .filter(Diagnosis.payment_id == payment.payment_id)
        .first()
    )

    if existing:
        existing.cause = cause
        existing.diagnosed_at = datetime.utcnow()
        diagnosis = existing
    else:
        diagnosis = Diagnosis(
            payment_id=payment.payment_id,
            cause=cause,
            diagnosed_at=datetime.utcnow(),
        )
        db.add(diagnosis)

    db.commit()
    db.refresh(diagnosis)
    return diagnosis


def diagnose_all_pending(db: Session) -> list[Diagnosis]:
    """
    Runs diagnosis on every payment that doesn't have one yet.
    This is what Day 2 DoD checks: 100% of ingested payments get a cause.
    """
    payments = db.query(Payment).all()
    results = []
    for payment in payments:
        results.append(diagnose_and_store(db, payment))
    return results
