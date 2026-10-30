"""
Case-wide and retry-specific eligibility checks.
Run before recovery scoring or execution. Deterministic rules only, no ML.
"""

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.models import Action

# Razorpay states where a retry is never the right action -
# per spec Section 11 / Rules.md, grounded in Razorpay's documented
# card-subscription state transitions.
NON_RETRYABLE_STATES = {
    "captured",    # already succeeded - nothing to retry
    "authorized",  # already succeeded - nothing to retry
    "halted",      # Razorpay's own auto-retries exhausted; customer must re-auth
}

TERMINAL_RECOVERY_STATES = {
    "captured", "authorized", "recovered", "closed_unrecovered",
}


def is_recovery_eligible(payment) -> tuple[bool, str]:
    """Case-wide restrictions shared by every recovery action."""
    for field in ("status", "razorpay_state"):
        state = (getattr(payment, field, None) or "").strip().lower()
        if state in TERMINAL_RECOVERY_STATES:
            return False, f"recovery not attempted: {field} is '{state}'"

    created_at = payment.created_at
    if created_at is None:
        return False, "recovery not attempted: payment creation time is missing"
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now - created_at >= timedelta(days=settings.max_recovery_window_days):
        return False, (
            f"recovery not attempted: recovery window of "
            f"{settings.max_recovery_window_days} days expired"
        )
    return True, "recovery eligible"


def _count_previous_retries(db, payment_id: str) -> int:
    return (
        db.query(Action)
        .filter(Action.payment_id == payment_id, Action.action_type == "retry")
        .count()
    )


def _hours_since_last_retry(db, payment_id: str):
    last_action = (
        db.query(Action)
        .filter(Action.payment_id == payment_id, Action.action_type == "retry")
        .order_by(Action.chosen_at.desc())
        .first()
    )
    if not last_action:
        return None
    delta = datetime.utcnow() - last_action.chosen_at
    return delta.total_seconds() / 3600


def is_retry_eligible(db, payment) -> tuple[bool, str]:
    """
    Returns (eligible: bool, reason: str).
    reason is always populated - used for the audit trail whether
    eligible or not (spec: every blocked retry needs an explicit reason).
    """

    eligible, reason = is_recovery_eligible(payment)
    if not eligible:
        return False, reason

    # 1. Razorpay state check
    state = (payment.razorpay_state or "").lower()
    if state in NON_RETRYABLE_STATES:
        return False, f"retry not attempted: payment/subscription in '{state}' state"

    # 2. Max retry attempts check (business-policy limit, bounded by
    # Razorpay's own T+1/T+2/T+3 support for card subscriptions)
    attempts_used = _count_previous_retries(db, payment.payment_id)
    if attempts_used >= settings.max_retry_attempts:
        return False, (
            f"retry not attempted: max retry attempts "
            f"({settings.max_retry_attempts}) already used"
        )

    # 3. Cooling-off period check
    hours_since = _hours_since_last_retry(db, payment.payment_id)
    if hours_since is not None and hours_since < settings.retry_cooling_off_hours:
        return False, (
            f"retry not attempted: cooling-off period active "
            f"({hours_since:.1f}h since last retry, needs {settings.retry_cooling_off_hours}h)"
        )

    return True, "retry eligible"
