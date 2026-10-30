from datetime import datetime

from sqlalchemy.orm import Session

from app.services.razorpay_client import client
from app.models.models import Payment


def fetch_and_store_payment(db: Session, payment_id: str) -> Payment:
    """
    Pulls a payment's real current state from Razorpay (test mode) and
    upserts it into the payments table with its real error_code,
    error_reason, and state.
    """
    rp_payment = client.payment.fetch(payment_id)

    existing = (
        db.query(Payment)
        .filter(Payment.payment_id == payment_id)
        .first()
    )

    error_code = rp_payment.get("error_code")
    error_reason = rp_payment.get("error_reason")
    status = rp_payment.get("status")
    method = rp_payment.get("method")
    provider_created_at = rp_payment.get("created_at")
    created_at = (
        datetime.utcfromtimestamp(provider_created_at)
        if provider_created_at is not None else None
    )

    if existing:
        existing.razorpay_error_code = error_code
        existing.razorpay_error_reason = error_reason
        # Provider status describes the original charge, not the recovery case.
        if existing.status not in {"recovered", "closed_unrecovered"}:
            existing.status = status
        if created_at is not None:
            existing.created_at = created_at
        existing.payment_method = method
        existing.razorpay_state = status
        payment = existing

    else:
        payment = Payment(
            payment_id=rp_payment["id"],
            order_id=rp_payment.get("order_id"),
            amount=rp_payment["amount"] / 100,
            payment_method=method,
            razorpay_error_code=error_code,
            razorpay_error_reason=error_reason,
            razorpay_state=status,
            status=status,
            created_at=created_at or datetime.utcnow(),
        )

        db.add(payment)

    db.commit()
    db.refresh(payment)

    return payment
