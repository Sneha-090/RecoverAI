import joblib

from pathlib import Path
from datetime import datetime

import pandas as pd

from app.models.models import Action, Customer
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

def predict_recovery(
    amount,
    cause,
    attempts,
    days_since_failure,
    past_rate,
    action_type,
):
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

DEFAULT_PAST_RATE = 0.5  # neutral assumption when no customer history exists


def _get_attempts_so_far(db, payment_id: str) -> int:
    """Counts how many actions have already been taken on this payment."""
    return (
        db.query(Action)
        .filter(Action.payment_id == payment_id)
        .count()
    )


def _get_past_rate(
    db,
    customer_id: str | None,
) -> float:
    """
    Looks up the customer's historical recovery rate.

    Falls back to a neutral default if no customer_id
    or no record exists.
    """
    if not customer_id:
        return DEFAULT_PAST_RATE

    customer = (
        db.query(Customer)
        .filter(Customer.customer_id == customer_id)
        .first()
    )

    if not customer or customer.previous_failures == 0:
        return DEFAULT_PAST_RATE

    return (
        customer.previous_recoveries
        / customer.previous_failures
    )


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

    past_rate = _get_past_rate(
        db,
        payment.customer_id,
    )

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

    return predictions