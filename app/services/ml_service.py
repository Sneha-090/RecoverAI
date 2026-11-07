import joblib

from pathlib import Path
from datetime import datetime

import pandas as pd

from app.models.models import Action
from app.services.customer_history import customer_history, DEFAULT_PAST_RATE
from app.services.diagnosis import diagnose


# -----------------------------
# Locate trained model
# -----------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_PATH = BASE_DIR / "ML" / "recovery_model.joblib"


# -----------------------------
# Load trained model
# -----------------------------

model = joblib.load(MODEL_PATH)


# -----------------------------
# Predict recovery probability for ONE action
# -----------------------------

class UnsupportedRecoveryCause(ValueError):
    """The saved estimator has no action-specific training support for this cause."""


def supported_recovery_causes():
    """Read coverage from the fitted encoder, including every candidate action."""
    encoder = model.named_steps["preprocessor"].named_transformers_["categorical"]
    causes, actions, interactions = map(set, encoder.categories_)
    return frozenset(cause for cause in causes
                     if set(CANDIDATE_ACTIONS).issubset(actions)
                     and all(f"{cause}__{action}" in interactions for action in CANDIDATE_ACTIONS))


def predict_recovery(
    amount,
    cause,
    attempts,
    days_since_failure,
    past_rate,
    action_type,
):
    if cause not in supported_recovery_causes():
        raise UnsupportedRecoveryCause("No trained action coverage for this failure cause")
    data = pd.DataFrame([{
        "amount": amount,
        "cause": cause,
        "attempts": attempts,
        "days_since_failure": days_since_failure,
        "past_rate": past_rate,
        "action_type": action_type,
    }])

    # Must match the feature engineering used during training.
    data["cause_action"] = (
        data["cause"] + "__" + data["action_type"]
    )

    probability = model.predict_proba(data)[0][1]

    return float(probability)


# -----------------------------
# Predict recovery probability for ALL candidate actions
# -----------------------------

CANDIDATE_ACTIONS = [
    "retry",
    "payment_link",
    "alt_method",
]


def _get_attempts_so_far(db, payment_id: str) -> int:
    """Count executed actions, including approvals; recommendations are not attempts."""
    return (
        db.query(Action)
        .filter(Action.payment_id == payment_id, Action.decision_type == "auto")
        .count()
    )


def _get_past_rate(db, customer_id, current_payment_id=None):
    return customer_history(db, customer_id, current_payment_id)['past_rate']


class RecoveryPredictions(dict):
    """Normal probability mapping carrying the exact non-identifying feature snapshot."""

    def __init__(self, values, context):
        super().__init__(values)
        self.context = context


def _get_days_since_failure(payment) -> int:
    delta = datetime.utcnow() - payment.created_at
    return max(delta.days, 0)


def predict_all_actions(db, payment) -> dict:
    """
    Given a Payment row, returns recovery probability
    for every candidate action:

    {
        "retry": ...,
        "payment_link": ...,
        "alt_method": ...
    }
    """
    cause = diagnose(payment)

    attempts = _get_attempts_so_far(
        db,
        payment.payment_id,
    )

    days_since_failure = _get_days_since_failure(
        payment
    )

    history = customer_history(db, payment.customer_id, payment.payment_id)
    past_rate = history['past_rate']

    predictions = {}

    for action_type in CANDIDATE_ACTIONS:
        predictions[action_type] = predict_recovery(
            amount=payment.amount,
            cause=cause,
            attempts=attempts,
            days_since_failure=days_since_failure,
            past_rate=past_rate,
            action_type=action_type,
        )

    return RecoveryPredictions(predictions, {
        'amount':payment.amount, 'cause':cause, 'executed_attempts':attempts,
        'days_since_failure':days_since_failure, 'past_rate':past_rate,
        'history_cases':history['finalized_cases'], 'uses_default_history':history['uses_default'],
    })