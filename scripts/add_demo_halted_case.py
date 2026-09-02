"""
Adds 1 demonstration payment in Razorpay's 'halted' state - retry is
ineligible per Section 11, so the system must fall back to another
action instead of blindly retrying. Day 8 demo scenario 3.
"""

from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.models.models import Payment, Diagnosis
from app.services.execution import execute_action

if __name__ == "__main__":
    db = SessionLocal()

    payment_id = f"sim_halted_{int(datetime.utcnow().timestamp())}"
    payment = Payment(
        payment_id=payment_id,
        order_id="sim_order_halted",
        amount=1499.0,
        payment_method="card",
        razorpay_error_code="SIMULATED",
        razorpay_state="halted",  # Razorpay's own auto-retries already exhausted
        status="failed",
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    db.add(payment)
    db.commit()

    diagnosis = Diagnosis(payment_id=payment_id, cause="bank_declined", diagnosed_at=datetime.utcnow())
    db.add(diagnosis)
    db.commit()

    result = execute_action(db, payment)
    print(f"{payment_id}: razorpay_state=halted, decision={result['decision_type']}, chosen_action={result.get('chosen_action')}, reason={result['reason']}")

    db.close()