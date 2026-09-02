"""
Adds 2 demonstration payments that deterministically route to
human_review (amount > Rs.50,000 threshold, guaranteed regardless of
confidence), so the Human-Approval Queue UI has real data to show
before the Day 8 demo. One stays pending (normal case), one is made
overdue and expired (timeout scenario - Day 8's second demo case).
"""

from datetime import datetime, timedelta

from app.db.session import SessionLocal
from app.models.models import Payment, Diagnosis
from app.services.execution import execute_action
from app.services.escalation import expire_overdue_reviews


def add_demo_case(db, suffix, amount, cause):
    payment_id = f"sim_hr_{suffix}_{int(datetime.utcnow().timestamp())}"
    payment = Payment(
        payment_id=payment_id,
        order_id=f"sim_order_hr_{suffix}",
        amount=amount,
        payment_method="card",
        razorpay_error_code="SIMULATED",
        razorpay_state="failed",
        status="failed",
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add(payment)
    db.commit()

    diagnosis = Diagnosis(payment_id=payment_id, cause=cause, diagnosed_at=datetime.utcnow())
    db.add(diagnosis)
    db.commit()

    result = execute_action(db, payment)
    print(f"{payment_id}: amount=Rs.{amount}, decision={result['decision_type']}, chosen_action={result.get('chosen_action')}")
    return payment_id


if __name__ == "__main__":
    db = SessionLocal()

    print("=== Adding demo human_review cases ===")
    pending_id = add_demo_case(db, "pending", amount=65000, cause="bank_declined")
    overdue_id = add_demo_case(db, "overdue", amount=88000, cause="card_declined")

    # Force the second case's deadline into the past, to demo the timeout flow
    from app.models.models import Action
    overdue_action = db.query(Action).filter(Action.payment_id == overdue_id).first()
    overdue_action.review_deadline = datetime.utcnow() - timedelta(hours=2)
    overdue_action.chosen_at = datetime.utcnow() - timedelta(hours=26)
    overdue_action.escalated_at = datetime.utcnow() - timedelta(hours=26)
    db.commit()
    print(f"{overdue_id}: deadline manually backdated to simulate an overdue case")

    print("\n=== Running escalation scheduler ===")
    expired = expire_overdue_reviews(db)
    print(f"Expired {len(expired)} overdue review(s)")

    db.close()