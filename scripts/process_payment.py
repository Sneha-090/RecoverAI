"""
Manual demo trigger - run this AFTER a checkout attempt, pasting the
payment_id that Razorpay's popup showed you.

Runs the full RecoverAI pipeline: fetch from Razorpay -> diagnose ->
decide -> execute.
"""

import sys

from app.db.session import SessionLocal
from app.services.ingestion import fetch_and_store_payment
from app.services.diagnosis import diagnose_and_store
from app.services.execution import execute_action

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.process_payment <payment_id>")
        sys.exit(1)

    payment_id = sys.argv[1]
    db = SessionLocal()

    print(f"\n=== Fetching payment from Razorpay: {payment_id} ===")
    payment = fetch_and_store_payment(db, payment_id)
    print(f"Amount: Rs.{payment.amount}")
    print(f"Error code: {payment.razorpay_error_code}")
    print(f"Error reason: {payment.razorpay_error_reason}")
    print(f"Razorpay status: {payment.status}")

    print("\n=== Running diagnosis ===")
    diagnosis = diagnose_and_store(db, payment)
    print(f"Diagnosed cause: {diagnosis.cause}")

    print("\n=== Running decision engine + execution ===")
    result = execute_action(db, payment)
    print(f"Chosen action: {result['chosen_action']}")
    print(f"Decision type: {result['decision_type']}")
    print(f"Reason: {result['reason']}")
    print(f"Executed: {result['executed']}")
    if result.get("razorpay_payload"):
        print(f"Razorpay reference: {result['razorpay_payload']}")

    db.close()