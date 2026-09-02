"""
Day 6: Batch simulation - samples N rows from the synthetic dataset,
inserts them as real Payment rows, runs the FULL real pipeline
(diagnose -> predict -> score -> decide) on each using the actual
trained model and decision engine, and simulates the outcome instead
of calling real Razorpay (since these aren't real payment IDs).

Includes a simulated observe/re-score loop per payment - mirrors the
real observe_outcome() loop from execution.py, but substitutes a
simulated outcome instead of a real Razorpay API check (since sim_
payment IDs don't exist in Razorpay).
"""

import random
from datetime import datetime, timedelta

import pandas as pd

from app.db.session import SessionLocal
from app.models.models import Payment, Diagnosis, Action, Outcome, AuditLog, DecisionType
from app.services.decision import decide

random.seed(42)

BATCH_SIZE = 75
MAX_ACTIONS_PER_PAYMENT = 3  # only 3 candidate actions exist total


def load_batch_sample():
    df = pd.read_csv("data/synthetic_payments.csv")
    return df.sample(n=BATCH_SIZE, random_state=42).reset_index(drop=True)


def simulate_outcome(chosen_action, row) -> str:
    """
    If the model's chosen action matches the synthetic row's original
    action_type, use that row's real recorded outcome. Otherwise,
    treat it as unobserved and use a coin-flip stand-in.
    """
    if chosen_action == row["action_type"]:
        return "success" if row["recovered"] == 1 else "failed"
    return "success" if random.random() < 0.25 else "failed"


def process_payment(db, payment, row):
    """
    Runs the full observe/re-score loop for one payment: decide -> log
    action -> simulate outcome -> if failed, decide() again (tried
    action auto-excluded) -> repeat until recovered, no candidates
    left, or MAX_ACTIONS_PER_PAYMENT reached.
    """
    for attempt_num in range(MAX_ACTIONS_PER_PAYMENT):
        decision = decide(db, payment)

        if decision["decision_type"] == "skip":
            entry = AuditLog(
                payment_id=payment.payment_id, timestamp=datetime.utcnow(),
                event_type="skipped", reason=decision["reason"],
            )
            db.add(entry)
            db.commit()
            if attempt_num == 0:
                payment.status = "failed"
            else:
                payment.status = "closed_unrecovered"
            db.commit()
            return

        if decision["decision_type"] == "human_review":
            action_row = Action(
                payment_id=payment.payment_id, action_type=decision["chosen_action"],
                chosen_at=datetime.utcnow(), decision_type=DecisionType.human_review,
            )
            db.add(action_row)
            db.commit()
            return  # awaiting human action - not part of the auto-loop

        # auto-execute (simulated)
        action_row = Action(
            payment_id=payment.payment_id, action_type=decision["chosen_action"],
            chosen_at=datetime.utcnow(), decision_type=DecisionType.auto,
        )
        db.add(action_row)
        db.commit()

        result = simulate_outcome(decision["chosen_action"], row)
        outcome_row = Outcome(
            payment_id=payment.payment_id, action_type=decision["chosen_action"],
            observed_result=result, observed_at=datetime.utcnow(),
        )
        db.add(outcome_row)

        if result == "success":
            payment.status = "recovered"
            db.commit()
            return  # loop stops - recovered

        # failed - loop continues, next decide() call will exclude this action
        payment.status = "failed"
        db.commit()

    # exhausted MAX_ACTIONS_PER_PAYMENT attempts without recovering
    payment.status = "closed_unrecovered"
    db.commit()


def run_batch():
    db = SessionLocal()
    batch = load_batch_sample()

    for i, row in batch.iterrows():
        payment_id = f"sim_{i:04d}_{int(datetime.utcnow().timestamp())}"
        created_at = datetime.utcnow() - timedelta(days=int(row["days_since_failure"]))

        payment = Payment(
            payment_id=payment_id,
            order_id=f"sim_order_{i:04d}",
            amount=float(row["amount"]),
            payment_method="card",
            razorpay_error_code="SIMULATED",
            razorpay_state="failed",
            status="failed",
            created_at=created_at,
        )
        db.add(payment)
        db.commit()

        diagnosis = Diagnosis(payment_id=payment_id, cause=row["cause"], diagnosed_at=datetime.utcnow())
        db.add(diagnosis)
        db.commit()

        process_payment(db, payment, row)

    db.close()
    print(f"Batch simulation complete: {BATCH_SIZE} payments processed (with observe/re-score loop).")


if __name__ == "__main__":
    run_batch()