import hashlib
import hmac
from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.db.session import SessionLocal
from app.models.models import Action, DecisionType, ReviewStatus
from app.services.diagnosis import diagnose_and_store
from app.services.execution import execute_action
from app.services.ingestion import fetch_and_store_payment

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_razorpay_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
):
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay webhook signature",
        )

    body = await request.body()

    if not verify_razorpay_signature(body, x_razorpay_signature):
        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay webhook signature",
        )

    payload = await request.json()
    event = payload.get("event")

    # We currently process only failed-payment events.
    if event != "payment.failed":
        return {
            "status": "ignored",
            "event": event,
        }

    payment_entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    payment_id = payment_entity.get("id")

    if not payment_id:
        raise HTTPException(
            status_code=400,
            detail="payment.failed event missing payment id",
        )

    db = SessionLocal()

    try:
        payment = fetch_and_store_payment(db, payment_id)

        # Prevent a duplicate/re-delivered webhook from creating
        # another recovery action for the same payment.
        recent_action = (
            db.query(Action)
            .filter(
                Action.payment_id == payment_id,
                Action.chosen_at
                >= datetime.utcnow() - timedelta(minutes=10),
            )
            .order_by(Action.chosen_at.desc())
            .first()
        )

        if recent_action:
            if (
                recent_action.decision_type == DecisionType.human_review
                and recent_action.review_status == ReviewStatus.pending
            ):
                return {
                    "status": "already_processing",
                    "payment_id": payment_id,
                    "reason": "Existing human-review action is still pending.",
                }

            return {
                "status": "already_processing",
                "payment_id": payment_id,
                "reason": "A recent recovery action already exists for this payment.",
            }

        diagnosis = diagnose_and_store(db, payment)
        result = execute_action(db, payment)

        return {
            "status": "processed",
            "payment_id": payment.payment_id,
            "diagnosed_cause": diagnosis.cause,
            "chosen_action": result["chosen_action"],
            "decision_type": result["decision_type"],
            "executed": result["executed"],
        }

    finally:
        db.close()