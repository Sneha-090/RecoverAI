from datetime import datetime

from sqlalchemy.orm import Session

from app.services.razorpay_client import client
from app.models.models import Payment


def fetch_and_store_payment(db: Session, payment_id: str) -> Payment:
    """
    Pulls a payment's real current state from Razorpay (test mode) and
    upserts it into the payments table with its real error_code + state.
    """
    rp_payment = client.payment.fetch(payment_id)

    existing = db.query(Payment).filter(Payment.payment_id == payment_id).first()

    error_code = rp_payment.get("error_code")
    status = rp_payment.get("status")  # created / authorized / captured / failed
    method = rp_payment.get("method")

    if existing:
        existing.razorpay_error_code = error_code
        existing.status = status
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
            razorpay_state=status,
            status=status,
            created_at=datetime.utcnow(),
        )
        db.add(payment)

    db.commit()
    db.refresh(payment)
    return payment