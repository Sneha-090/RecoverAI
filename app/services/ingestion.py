from datetime import datetime
import re
from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import Session

from app.services.razorpay_client import client, ProviderReadUnavailable
from requests.exceptions import ConnectionError, Timeout
from app.models.models import Payment, Customer


class PaymentLookupUnavailable(ProviderReadUnavailable):
    """The initial provider GET failed before any local payment mutation."""


def fetch_and_store_payment(db: Session, payment_id: str) -> Payment:
    """
    Pulls a payment's real current state from Razorpay (test mode) and
    upserts it into the payments table with its real error_code,
    error_reason, and state.
    """
    try:
        rp_payment = client.payment.fetch(payment_id)
    except (ProviderReadUnavailable, ConnectionError, Timeout) as error:
        raise PaymentLookupUnavailable('Payment lookup temporarily unavailable before ingestion') from error

    existing = (
        db.query(Payment)
        .filter(Payment.payment_id == payment_id)
        .first()
    )

    provider_order_id = rp_payment.get('order_id') or None
    if existing and existing.order_id and provider_order_id != existing.order_id:
        raise ValueError('Original provider order reference changed; operator investigation required')

    customer_id = rp_payment.get("customer_id") or None
    if customer_id is not None and (not isinstance(customer_id, str)
            or not re.fullmatch(r"cust_[A-Za-z0-9]{1,64}", customer_id)):
        raise ValueError("Provider customer reference is invalid")
    if existing and existing.customer_id and customer_id and existing.customer_id != customer_id:
        raise ValueError("Provider customer reference changed; operator investigation required")
    if customer_id and db.get(Customer, customer_id) is None:
        try:
            with db.begin_nested():
                db.add(Customer(customer_id=customer_id))
                db.flush()
        except IntegrityError:
            if db.get(Customer, customer_id) is None:
                raise

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
        if provider_order_id:
            existing.order_id = provider_order_id
        if customer_id:
            existing.customer_id = customer_id
        existing.razorpay_error_code = error_code
        existing.razorpay_error_reason = error_reason
        # Provider status describes the original charge, not the recovery case.
        if existing.status not in {"recovered", "closed_unrecovered", "paid_original", "needs_reconciliation"}:
            existing.status = status
        if created_at is not None:
            existing.created_at = created_at
        existing.payment_method = method
        existing.razorpay_state = status
        payment = existing

    else:
        payment = Payment(
            payment_id=rp_payment["id"],
            customer_id=customer_id,
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
