"""
Human-review timeout scheduler - Section 12/14 of spec.
NEVER auto-authorizes a risky action on timeout - only marks the case
expired and logs it.
"""

from datetime import datetime

from app.models.models import Action, DecisionType, ReviewStatus, AuditLog


def expire_overdue_reviews(db) -> list:
    now = datetime.utcnow()
    overdue = (
        db.query(Action)
        .filter(
            Action.decision_type == DecisionType.human_review,
            Action.review_status == ReviewStatus.pending,
            Action.review_deadline < now,
        )
        .all()
    )

    for action in overdue:
        action.review_status = ReviewStatus.expired
        entry = AuditLog(
            payment_id=action.payment_id,
            timestamp=now,
            event_type="human_review_expired",
            reason=f"deadline {action.review_deadline} passed with no human action - no risky action auto-executed",
        )
        db.add(entry)

    db.commit()
    return overdue