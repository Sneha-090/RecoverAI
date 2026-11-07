"""
Cost-adjusted scoring + decision engine - Section 9/10 of spec.

Score(action) = P(action) x amount - cost(action), computed only for
actions that pass the eligibility check (Section 11) and have not
already been tried for this payment (Section 12's re-score loop).
"""

from datetime import datetime
import json

from app.config import settings
from app.services.ml_service import predict_all_actions, supported_recovery_causes, UnsupportedRecoveryCause
from app.services.diagnosis import diagnose
from app.services.policy import select_recovery_action
from app.services.eligibility import is_recovery_eligible, is_retry_eligible
from app.models.models import Action
from app.services.payment_methods import is_alt_method_eligible

ACTION_COSTS = {
    "retry": settings.action_cost_retry,
    "payment_link": settings.action_cost_payment_link,
    "alt_method": settings.action_cost_alt_method,
}


def score_action(probability: float, amount: float, action_type: str) -> float:
    cost = ACTION_COSTS[action_type]
    return probability * amount - cost


# =====================================================================
# UNCHANGED - pure function, no DB/ML calls, exactly as before.
# All 10 existing tests in test_decision.py continue to exercise this
# exact function, untouched, per requirement F.
# =====================================================================
def decide_from_predictions(
    payment,
    predictions: dict,
    retry_eligible: bool,
    retry_reason: str,
    excluded_actions: set | None = None,
) -> dict:
    return select_recovery_action(
        payment.amount, predictions, retry_eligible, retry_reason, excluded_actions,
        action_costs=ACTION_COSTS, score_floor=settings.score_floor,
        min_action_margin_ratio=settings.min_action_margin_ratio,
        human_review_amount_threshold=settings.human_review_amount_threshold,
    )


def get_tried_actions(db, payment_id: str) -> set:
    """
    Action types already EXECUTED (decision_type='auto') for this
    payment - excluded from re-scoring, and doubles as the simple
    duplicate-attempt guard (Section 13).
    """
    rows = (
        db.query(Action)
        .filter(Action.payment_id == payment_id, Action.decision_type == "auto")
        .all()
    )
    return {row.action_type for row in rows}


def _persist_decision_explanation(db, payment, predictions, retry_eligible, retry_reason, tried_actions, blocked_actions=None):
    """
    MODULE A - persistence only. Records what decide() already
    computed: the ML prediction for every action, and a cost-adjusted
    score + eligibility record for every action - regardless of which
    one ultimately won. Does NOT influence the decision in any way.

    Called once per decide() call, so the observe -> re-score loop
    produces a fresh, timestamped set of rows each time - nothing is
    overwritten, so the full decision history is preserved.
    """
    from app.models.models import MLPrediction, RecoveryScore

    now = datetime.utcnow()

    for action_type, probability in predictions.items():
        db.add(MLPrediction(
            payment_id=payment.payment_id,
            action_type=action_type,
            probability=probability,
            predicted_at=now,
        ))

    for action_type, probability in predictions.items():
        score = score_action(probability, payment.amount, action_type)

        if action_type == "retry":
            eligible = retry_eligible
            reason = retry_reason
        else:
            eligible = True
            reason = "eligible - no additional restrictions currently checked for this action"

        if action_type in (blocked_actions or {}):
            eligible = False
            reason = blocked_actions[action_type]
        if action_type in tried_actions:
            eligible = False
            reason = f"excluded from candidates - already tried in this recovery attempt ({reason})"

        db.add(RecoveryScore(
            payment_id=payment.payment_id,
            action_type=action_type,
            score=score,
            cost_used=ACTION_COSTS[action_type],
            retry_eligible=eligible,
            eligibility_reason=reason,
            evaluated_at=now,
        ))

    context = getattr(predictions, 'context', None)
    if context is not None:
        from app.models.models import AuditLog
        db.add(AuditLog(payment_id=payment.payment_id, timestamp=now,
                        event_type='decision_features', reason='Exact features used for recorded model probabilities',
                        payload_json=json.dumps(context, allow_nan=False)))
    db.commit()


def decide(db, payment) -> dict:
    """
    Reject ineligible cases before ML or scoring. For eligible cases,
    fetch predictions and already-tried actions, decide, and persist
    the explanation. execute_action() audits skipped cases.
    """
    eligible, reason = is_recovery_eligible(payment)
    if not eligible:
        return {"chosen_action": None, "decision_type": "skip", "reason": reason}

    cause = diagnose(payment)
    if cause not in supported_recovery_causes():
        return {
            "chosen_action": "manual_assessment", "decision_type": "human_review",
            "reason": f"Failure cause '{cause}' is outside the model's trained action coverage; "
                      "no ML recommendation or automatic recovery. Operator must assess and choose an action.",
        }

    retry_eligible, retry_reason = is_retry_eligible(db, payment)
    try:
        predictions = predict_all_actions(db, payment)
    except UnsupportedRecoveryCause as error:
        return {'chosen_action':'manual_assessment','decision_type':'human_review',
                'reason':str(error)}
    tried = get_tried_actions(db, payment.payment_id)
    alt_eligible, alt_reason = is_alt_method_eligible(payment)
    blocked = {} if alt_eligible else {"alt_method": alt_reason}

    decision = decide_from_predictions(payment, predictions, retry_eligible, retry_reason, excluded_actions=tried | set(blocked))

    _persist_decision_explanation(db, payment, predictions, retry_eligible, retry_reason, tried, blocked)

    return decision
