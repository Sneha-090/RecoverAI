"""
Live demo script - shows each pipeline step with visible output,
so the audience sees the engine working, not just a final result.
"""
import time
from datetime import datetime
from app.db.session import SessionLocal
from app.models.models import Payment, Diagnosis
from app.services.diagnosis import diagnose
from app.services.ml_service import predict_all_actions
from app.services.decision import decide
from app.services.execution import execute_action

db = SessionLocal()

print("\n=== STEP 1: New failed payment arrives ===")
payment = Payment(
    payment_id=f"demo_{int(datetime.utcnow().timestamp())}",
    order_id="demo_order_001",
    amount=2499.0,
    payment_method="card",
    razorpay_error_code="BAD_REQUEST_ERROR",
    razorpay_error_reason="insufficient_funds",
    razorpay_state="failed",
    status="failed",
    created_at=datetime.utcnow(),
)
db.add(payment)
db.commit()
print(f"Payment ID: {payment.payment_id}")
print(f"Amount: Rs.{payment.amount}")
print(f"Error: {payment.razorpay_error_code} / {payment.razorpay_error_reason}")
time.sleep(2)

print("\n=== STEP 2: Diagnosis engine runs ===")
cause = diagnose(payment)
diagnosis = Diagnosis(payment_id=payment.payment_id, cause=cause, diagnosed_at=datetime.utcnow())
db.add(diagnosis)
db.commit()
print(f"Diagnosed cause: {cause}")
time.sleep(2)

print("\n=== STEP 3: ML model predicts recovery probability for each action ===")
predictions = predict_all_actions(db, payment)
for action, prob in predictions.items():
    print(f"  {action}: {prob:.2%}")
time.sleep(2)

print("\n=== STEP 4: Decision engine scores + decides ===")
decision = decide(db, payment)
print(f"Chosen action: {decision['chosen_action']}")
print(f"Decision type: {decision['decision_type']}")
print(f"Reason: {decision['reason']}")
time.sleep(2)

print("\n=== STEP 5: Executing (real Razorpay call for auto-decisions) ===")
result = execute_action(db, payment)
print(f"Executed: {result['executed']}")
if result.get('razorpay_payload'):
    print(f"Razorpay reference: {result['razorpay_payload']}")

print(f"\nDone. Check the dashboard for payment_id: {payment.payment_id}")
db.close()