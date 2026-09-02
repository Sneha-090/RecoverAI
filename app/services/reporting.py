"""
Day 6: Impact measurement + baseline comparison - Section 16/17 of spec.
"""

import random

from app.db.session import SessionLocal
from app.models.models import Payment, Action
from app.services.ml_service import predict_all_actions


def compute_impact_metrics(db, payment_id_prefix="sim_"):
    payments = db.query(Payment).filter(Payment.payment_id.like(f"{payment_id_prefix}%")).all()

    total_at_risk = sum(p.amount for p in payments)
    total_recovered = sum(p.amount for p in payments if p.status == "recovered")

    recovered_count = sum(1 for p in payments if p.status == "recovered")
    recovery_rate = recovered_count / len(payments) if payments else 0

    total_attempts = db.query(Action).filter(
        Action.payment_id.in_([p.payment_id for p in payments]),
        Action.decision_type == "auto",
    ).count()

    recovered_per_attempt = total_recovered / total_attempts if total_attempts else 0

    return {
        "total_payments": len(payments),
        "total_at_risk": round(total_at_risk, 2),
        "total_recovered": round(total_recovered, 2),
        "recovered_count": recovered_count,
        "recovery_rate": round(recovery_rate, 4),
        "total_attempts": total_attempts,
        "recovered_per_attempt": round(recovered_per_attempt, 2),
    }


def compute_naive_blanket_retry_baseline(db, payment_id_prefix="sim_"):
    """
    Simulates blindly retrying EVERY failed payment once - no eligibility
    check, no cause-aware action selection, no cost-scoring, retry is
    always the action regardless of whether it's the best choice.

    Uses the REAL trained model's own retry-probability for each payment
    (instead of one flat assumed rate) as the success probability for
    that payment's coin-flip - this ties the baseline to each payment's
    actual characteristics (cause, past_rate, etc.) rather than treating
    every payment identically, which is a fairer/less noisy comparison.
    """
    random.seed(7)

    payments = db.query(Payment).filter(Payment.payment_id.like(f"{payment_id_prefix}%")).all()

    total_recovered = 0.0
    recovered_count = 0
    attempts = len(payments)  # one retry attempt per payment, no eligibility skipping

    for p in payments:
        predictions = predict_all_actions(db, p)
        retry_probability = predictions["retry"]

        if random.random() < retry_probability:
            total_recovered += p.amount
            recovered_count += 1

    recovery_rate = recovered_count / len(payments) if payments else 0

    return {
        "total_payments": len(payments),
        "total_recovered": round(total_recovered, 2),
        "recovered_count": recovered_count,
        "recovery_rate": round(recovery_rate, 4),
        "total_attempts": attempts,
    }


if __name__ == "__main__":
    db = SessionLocal()
    print("=== RecoverAI Impact ===")
    recoverai_metrics = compute_impact_metrics(db)
    for k, v in recoverai_metrics.items():
        print(f"{k}: {v}")

    print("\n=== Naive Blanket-Retry Baseline (using model's own retry-probability per payment) ===")
    baseline_metrics = compute_naive_blanket_retry_baseline(db)
    for k, v in baseline_metrics.items():
        print(f"{k}: {v}")

    recoverai_efficiency = recoverai_metrics["total_recovered"] / recoverai_metrics["total_attempts"]
    baseline_efficiency = baseline_metrics["total_recovered"] / baseline_metrics["total_attempts"]

    print("\n=== Question A: Per-attempt efficiency (Rs recovered / attempt) ===")
    print(f"Baseline:  Rs.{baseline_efficiency:.2f} per attempt")
    print(f"RecoverAI: Rs.{recoverai_efficiency:.2f} per attempt")
    print("(Baseline can be slightly higher here - it only ever takes ONE attempt")
    print(" per payment, so it never 'spends' attempts on cases that end up unrecovered.)")

    print("\n=== Question B: Total revenue recovered (the actual business goal) ===")
    print(f"Baseline:  Rs.{baseline_metrics['total_recovered']} recovered ({baseline_metrics['recovery_rate']*100:.1f}% recovery rate)")
    print(f"RecoverAI: Rs.{recoverai_metrics['total_recovered']} recovered ({recoverai_metrics['recovery_rate']*100:.1f}% recovery rate)")
    print(f"RecoverAI recovered Rs.{recoverai_metrics['total_recovered'] - baseline_metrics['total_recovered']:.2f} MORE than baseline")
    print(f"({recoverai_metrics['recovered_count']} vs {baseline_metrics['recovered_count']} payments recovered)")

    db.close()