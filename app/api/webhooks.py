import hashlib
import hmac
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.db.session import SessionLocal
from app.models.models import (
    Action,
    AuditLog,
    DecisionType,
    ReviewStatus,
    Payment,
)
from app.services.diagnosis import diagnose_and_store
from app.services.execution import execute_action, observe_outcome
from app.services.ingestion import fetch_and_store_payment


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_razorpay_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def _find_recovery_case_by_order_id(db, order_id: str):
    """
    Find the original RecoverAI payment whose recovery action
    created the given Razorpay order.

    Both automatic and human-approved executions are considered.
    The latest matching execution is returned.
    """
    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type.in_(
                ["executed", "human_approved_executed"]
            )
        )
        .order_by(
            AuditLog.timestamp.desc(),
            AuditLog.id.desc(),
        )
        .all()
    )

    for entry in entries:
        if not entry.payload_json:
            continue

        try:
            payload = json.loads(entry.payload_json)
        except (TypeError, json.JSONDecodeError):
            continue

        if (
            payload.get("type") == "order"
            and payload.get("order_id") == order_id
        ):
            return entry.payment_id

    return None


def _find_recovery_case_by_payment_link_description(
    db,
    description: str,
):
    """
    Find the original RecoverAI payment associated with a
    Razorpay Payment Link captured-payment description.

    In the observed Razorpay Test Mode payload, the Payment Link
    reference appeared in the payment description as:

        #<payment_link_id_without_plink_prefix>
    """
    if not description:
        return None

    normalized_description = description.strip()

    if not normalized_description.startswith("#"):
        return None

    link_suffix = normalized_description[1:].strip()

    if not link_suffix:
        return None

    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type.in_(
                ["executed", "human_approved_executed"]
            )
        )
        .order_by(
            AuditLog.timestamp.desc(),
            AuditLog.id.desc(),
        )
        .all()
    )

    for entry in entries:
        if not entry.payload_json:
            continue

        try:
            payload = json.loads(entry.payload_json)
        except (TypeError, json.JSONDecodeError):
            continue

        if payload.get("type") != "payment_link":
            continue

        payment_link_id = payload.get("payment_link_id")

        if not payment_link_id:
            continue

        normalized_link_id = payment_link_id.removeprefix("plink_")

        if normalized_link_id == link_suffix:
            return entry.payment_id

    return None


def _webhook_event_already_processed(db, razorpay_event_id: str) -> bool:
    """
    Check whether this exact Razorpay webhook event ID was already
    recorded as processed.
    """
    if not razorpay_event_id:
        return False

    existing_event = (
        db.query(AuditLog)
        .filter(
            AuditLog.razorpay_event_id == razorpay_event_id
        )
        .first()
    )

    return existing_event is not None


def _record_processed_webhook(
    db,
    payment_id: str,
    event_type: str,
    razorpay_event_id: str | None,
    payload: dict,
):
    """
    Record a successfully processed Razorpay webhook event.
    """
    if not razorpay_event_id:
        return

    entry = AuditLog(
        payment_id=payment_id,
        timestamp=datetime.utcnow(),
        event_type="webhook_processed",
        reason=event_type,
        payload_json=json.dumps(payload),
        razorpay_event_id=razorpay_event_id,
    )

    db.add(entry)
    db.commit()


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
):
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay webhook signature",
        )

    body = await request.body()

    if not verify_razorpay_signature(
        body,
        x_razorpay_signature,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay webhook signature",
        )

    payload = await request.json()
    event = payload.get("event")
    razorpay_event_id = x_razorpay_event_id

    # Temporary debugging output while validating Razorpay webhooks.
    print("\n===== RAZORPAY WEBHOOK PAYLOAD =====")
    print(json.dumps(payload, indent=2))
    print("====================================\n")

    # Ignore events that this application does not handle.
    if event not in {"payment.captured", "payment.failed"}:
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
            detail=f"{event} event missing payment id",
        )

    db = SessionLocal()

    try:
        # -----------------------------------------------------
        # IDEMPOTENCY CHECK
        # -----------------------------------------------------
        if _webhook_event_already_processed(
            db,
            razorpay_event_id,
        ):
            return {
                "status": "already_processed",
                "razorpay_event_id": razorpay_event_id,
                "event": event,
            }

        # -----------------------------------------------------
        # PAYMENT CAPTURED
        # -----------------------------------------------------
        if event == "payment.captured":
            captured_payment_id = payment_entity.get("id")
            recovery_order_id = payment_entity.get("order_id")
            payment_description = payment_entity.get("description")

            original_payment_id = None

            # First try order-based recovery matching.
            if recovery_order_id:
                original_payment_id = _find_recovery_case_by_order_id(
                    db,
                    recovery_order_id,
                )

            # If not found, try Payment Link matching.
            if not original_payment_id and payment_description:
                original_payment_id = (
                    _find_recovery_case_by_payment_link_description(
                        db,
                        payment_description,
                    )
                )

            if not original_payment_id:
                return {
                    "status": "ignored",
                    "reason": (
                        "Captured payment does not belong to a "
                        "RecoverAI recovery action."
                    ),
                    "captured_payment_id": captured_payment_id,
                    "order_id": recovery_order_id,
                    "description": payment_description,
                }

            original_payment = (
                db.query(Payment)
                .filter(
                    Payment.payment_id == original_payment_id
                )
                .first()
            )

            if not original_payment:
                return {
                    "status": "ignored",
                    "reason": "Original RecoverAI payment not found.",
                }

            result = observe_outcome(
                db,
                original_payment,
            )

            _record_processed_webhook(
                db=db,
                payment_id=original_payment.payment_id,
                event_type=event,
                razorpay_event_id=razorpay_event_id,
                payload=payload,
            )

            return {
                "status": "outcome_observed",
                "payment_id": original_payment.payment_id,
                "captured_payment_id": captured_payment_id,
                "order_id": recovery_order_id,
                "description": payment_description,
                "outcome": result,
            }

        # -----------------------------------------------------
        # PAYMENT FAILED
        # -----------------------------------------------------
        recovery_order_id = payment_entity.get("order_id")

        # First determine whether this failed payment belongs
        # to an existing RecoverAI recovery action.
        original_payment_id = None

        if recovery_order_id:
            original_payment_id = _find_recovery_case_by_order_id(
                db,
                recovery_order_id,
            )

        # Recovery attempt failed.
        # Do NOT create a new independent RecoverAI case.
        if original_payment_id and original_payment_id != payment_id:
            original_payment = (
                db.query(Payment)
                .filter(
                    Payment.payment_id == original_payment_id
                )
                .first()
            )

            if original_payment:
                result = observe_outcome(
                    db,
                    original_payment,
                )

                _record_processed_webhook(
                    db=db,
                    payment_id=original_payment.payment_id,
                    event_type=event,
                    razorpay_event_id=razorpay_event_id,
                    payload=payload,
                )

                return {
                    "status": "recovery_attempt_processed",
                    "recovery_payment_id": payment_id,
                    "recovery_order_id": recovery_order_id,
                    "original_payment_id": original_payment.payment_id,
                    "outcome": result,
                }

        # Normal original payment failure.
        payment = fetch_and_store_payment(
            db,
            payment_id,
        )

        # Prevent duplicate/re-delivered webhook processing for
        # the same payment using the existing recent-action guard.
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
                recent_action.decision_type
                == DecisionType.human_review
                and recent_action.review_status
                == ReviewStatus.pending
            ):
                return {
                    "status": "already_processing",
                    "payment_id": payment_id,
                    "reason": (
                        "Existing human-review action is still pending."
                    ),
                }

            return {
                "status": "already_processing",
                "payment_id": payment_id,
                "reason": (
                    "A recent recovery action already exists "
                    "for this payment."
                ),
            }

        diagnosis = diagnose_and_store(
            db,
            payment,
        )

        result = execute_action(
            db,
            payment,
        )

        _record_processed_webhook(
            db=db,
            payment_id=payment.payment_id,
            event_type=event,
            razorpay_event_id=razorpay_event_id,
            payload=payload,
        )

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