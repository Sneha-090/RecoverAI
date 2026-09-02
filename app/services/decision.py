"""
Cost-adjusted scoring + decision engine - Section 9/10 of spec.

Score(action) = P(action) x amount - cost(action), computed only for
actions that pass the eligibility check (Section 11) and have not
already been tried for this payment (Section 12's re-score loop).
"""

from datetime import datetime

from app.config import settings
from app.services.ml_service import predict_all_actions
from app.services.eligibility import is_retry_eligible
from app.models.models import Action

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
    excluded_actions = excluded_actions or set()

    candidates = {
        action: prob
        for action, prob in predictions.items()
        if action not in excluded_actions
    }
    if not retry_eligible:
        candidates.pop("retry", None)

    if not candidates:
        reason = retry_reason if not retry_eligible else "all candidate actions already tried"
        return {
            "chosen_action": None,
            "decision_type": "skip",
            "reason": f"no action remains eligible ({reason})",
        }

    scored = {
        action: score_action(prob, payment.amount, action)
        for action, prob in candidates.items()
    }

    best_action = max(scored, key=scored.get)
    best_score = scored[best_action]
    best_prob = candidates[best_action]

    if best_score <= settings.score_floor:
        return {
            "chosen_action": None,
            "decision_type": "skip",
            "reason": f"no eligible action scores above floor (best: {best_action} @ {best_score:.2f})",
        }

    in_confidence_band = settings.confidence_band_low <= best_prob <= settings.confidence_band_high
    high_value = payment.amount > settings.human_review_amount_threshold

    if in_confidence_band or high_value:
        reason_bits = []
        if in_confidence_band:
            reason_bits.append(
                f"confidence {best_prob:.2f} in uncertain band "
                f"[{settings.confidence_band_low}-{settings.confidence_band_high}]"
            )
        if high_value:
            reason_bits.append(
                f"amount {payment.amount} exceeds human-review threshold "
                f"{settings.human_review_amount_threshold}"
            )
        return {
            "chosen_action": best_action,
            "decision_type": "human_review",
            "reason": "; ".join(reason_bits),
        }

    return {
        "chosen_action": best_action,
        "decision_type": "auto",
        "reason": (
            f"best eligible action {best_action} scored {best_score:.2f} "
            f"(P={best_prob:.2f}), above threshold and outside uncertain band"
        ),
    }


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


def _persist_decision_explanation(db, payment, predictions, retry_eligible, retry_reason, tried_actions):
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

    db.commit()


def decide(db, payment) -> dict:
    """
    Wrapper: fetches real predictions + eligibility + already-tried
    actions, applies decide_from_predictions() to get the decision,
    then persists the full explanation (Module A) - purely additive,
    the returned decision is unaffected by the persistence step.
    """
    retry_eligible, retry_reason = is_retry_eligible(db, payment)
    predictions = predict_all_actions(db, payment)
    tried = get_tried_actions(db, payment.payment_id)

    decision = decide_from_predictions(payment, predictions, retry_eligible, retry_reason, excluded_actions=tried)

    _persist_decision_explanation(db, payment, predictions, retry_eligible, retry_reason, tried)

    return decision