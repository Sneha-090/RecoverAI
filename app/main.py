from app.api.webhooks import router as webhook_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.db.session import SessionLocal
from app.services.ml_service import predict_recovery
from app.services.order_service import create_test_order
from app.services.ingestion import fetch_and_store_payment
from app.services.diagnosis import diagnose_and_store
from app.services.execution import execute_action

app = FastAPI(title="RecoverAI")
app.include_router(webhook_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "human_review_timeout_hours": settings.human_review_timeout_hours,
        "max_recovery_window_days": settings.max_recovery_window_days,
    }


@app.get("/create-order")
def create_order(amount: float):
    """
    Creates a real Razorpay test-mode Order for the given amount (in
    rupees) and returns its order_id.
    """
    order = create_test_order(amount_rupees=amount, receipt=f"recoverai_{int(amount)}")
    return {"order_id": order["id"], "amount_paise": order["amount"]}


@app.get("/process-payment")
def process_payment(payment_id: str):
    """
    Full pipeline, triggered automatically after a checkout attempt:
    fetch real payment from Razorpay -> diagnose -> execute_action()
    (which internally calls decide() ONCE and acts on that same
    decision - no separate decide() call here, so the decision shown
    in the response is guaranteed to match what was actually executed).
    """
    db = SessionLocal()
    try:
        payment = fetch_and_store_payment(db, payment_id)
        diagnosis = diagnose_and_store(db, payment)

        result = execute_action(db, payment)

        return {
            "payment_id": payment.payment_id,
            "amount": payment.amount,
            "razorpay_status": payment.status,
            "razorpay_error_code": payment.razorpay_error_code,
            "razorpay_error_reason": payment.razorpay_error_reason,
            "diagnosed_cause": diagnosis.cause,
            "chosen_action": result["chosen_action"],
            "decision_type": result["decision_type"],
            "decision_reason": result["reason"],
            "executed": result["executed"],
            "razorpay_action_payload": result.get("razorpay_payload"),
        }
    finally:
        db.close()


# -----------------------------
# Prediction request format
# -----------------------------

class RecoveryRequest(BaseModel):
    amount: float
    cause: str
    attempts: int
    days_since_failure: int
    past_rate: float
    action_type: str


@app.post("/predict")
def predict(request: RecoveryRequest):
    probability = predict_recovery(
        amount=request.amount,
        cause=request.cause,
        attempts=request.attempts,
        days_since_failure=request.days_since_failure,
        past_rate=request.past_rate,
        action_type=request.action_type,
    )
    return {
        "recovery_probability": probability,
        "recovery_percentage": round(probability * 100, 2),
    }
@app.get("/latest-payment-for-order")
def latest_payment_for_order(order_id: str):
    """
    Recovers the payment_id for an order even if the browser reloaded
    mid-flow (e.g. redirect-based payment methods like netbanking) -
    fetches the order's payment attempts directly from Razorpay.
    """
    from app.services.razorpay_client import client
    payments = client.order.payments(order_id)
    items = payments.get("items", [])
    if not items:
        return {"payment_id": None}
    # most recent attempt
    latest = sorted(items, key=lambda p: p.get("created_at", 0), reverse=True)[0]
    return {"payment_id": latest["id"]}