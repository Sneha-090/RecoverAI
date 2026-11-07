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

# Broad error codes do not identify a root cause. Use explicit provider reasons.
# https://github.com/razorpay/markdown-docs/blob/master/payments/payment-gateway/rainy-day/errors/error-reasons.md
ERROR_REASON_CAUSE_MAP = {
    "payment_declined": "bank_declined",
    "insufficient_funds": "insufficient_funds",
    "card_declined": "card_declined",
    "expired_card": "expired_card",
    "card_expired": "expired_card",
    "invalid_card": "invalid_card",
    "incorrect_card_details": "invalid_card",
    "authentication_failed": "authentication_failed",
    "processing_error": "network_error",
    "issuer_unavailable": "network_error",
    "gateway_technical_error": "network_error",
    "issuer_technical_error": "network_error",
    "payment_cancelled": "customer_cancelled",
}

FALLBACK_CAUSE = "unclassified_error"


def diagnose(payment: Payment) -> str:
    """Preserve uncertainty when the provider has not supplied a specific reason.

    In particular, payment_failed, BAD_REQUEST_ERROR and GATEWAY_ERROR do not
    establish a bank decline. Unknown reasons require manual assessment.
    """
    reason = (getattr(payment, "razorpay_error_reason", None) or "").strip().lower()
    return ERROR_REASON_CAUSE_MAP.get(reason, FALLBACK_CAUSE)


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
