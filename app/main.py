from app.api.webhooks import router as webhook_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, Query, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.api.auth import require_operator

from app.config import settings
from app.db.session import SessionLocal
from app.services.ml_service import predict_recovery, UnsupportedRecoveryCause
from app.services.order_service import create_test_order
from app.services.ingestion import fetch_and_store_payment
from app.services.diagnosis import diagnose_and_store
from app.services.execution import execute_action

app = FastAPI(title="RecoverAI")
app.include_router(webhook_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

PROTECTED = [Depends(require_operator)]
PAYMENT_ID = r"^pay_[A-Za-z0-9]{1,64}$"
ORDER_ID = r"^order_[A-Za-z0-9]{1,64}$"


@app.middleware("http")
async def protect_browser_mutations(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method == "POST" and request.url.path in {"/create-order", "/process-payment", "/predict"}:
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin and origin != same_origin and origin not in settings.allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
    return await call_next(request)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, le=10_000_000, max_digits=10, decimal_places=2, allow_inf_nan=False)


class ProcessPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_id: str = Field(pattern=PAYMENT_ID)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "human_review_timeout_hours": settings.human_review_timeout_hours,
        "max_recovery_window_days": settings.max_recovery_window_days,
    }


@app.post("/create-order", dependencies=PROTECTED)
def create_order(request: OrderRequest):
    """
    Creates a real Razorpay test-mode Order for the given amount (in
    rupees) and returns its order_id.
    """
    order = create_test_order(amount_rupees=request.amount, receipt=f"recoverai_{int(request.amount)}")
    return {"order_id": order["id"], "amount_paise": order["amount"]}


@app.post("/process-payment", dependencies=PROTECTED)
def process_payment(request: ProcessPaymentRequest):
    """
    Full pipeline, triggered automatically after a checkout attempt:
    fetch real payment from Razorpay -> diagnose -> execute_action()
    (which internally calls decide() ONCE and acts on that same
    decision - no separate decide() call here, so the decision shown
    in the response is guaranteed to match what was actually executed).
    """
    db = SessionLocal()
    try:
        payment = fetch_and_store_payment(db, request.payment_id)
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
    model_config = ConfigDict(extra="forbid")
    amount: FiniteFloat = Field(gt=0, le=10_000_000)
    cause: Literal[
        "network_error", "insufficient_funds", "bank_declined", "card_declined",
        "expired_card", "invalid_card", "authentication_failed", "customer_cancelled", "unclassified_error",
    ]
    attempts: int = Field(ge=0, le=10_000)
    days_since_failure: int = Field(ge=0, le=36_500)
    past_rate: FiniteFloat = Field(ge=0, le=1)
    action_type: Literal["retry", "payment_link", "alt_method"]


@app.post("/predict", dependencies=PROTECTED)
def predict(request: RecoveryRequest):
    try:
        probability = predict_recovery(
            amount=request.amount, cause=request.cause, attempts=request.attempts,
            days_since_failure=request.days_since_failure, past_rate=request.past_rate,
            action_type=request.action_type,
        )
    except UnsupportedRecoveryCause:
        raise HTTPException(status_code=422, detail="This failure cause requires manual assessment; no trained prediction is available") from None
    return {
        "recovery_probability": probability,
        "recovery_percentage": round(probability * 100, 2),
    }
@app.get("/latest-payment-for-order", dependencies=PROTECTED)
def latest_payment_for_order(order_id: Annotated[str, Query(pattern=ORDER_ID)]):
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


@app.get("/checkout", dependencies=PROTECTED)
def checkout():
    return FileResponse(Path(__file__).resolve().parents[1] / "scripts/checkout.html")


@app.get("/checkout-config", dependencies=PROTECTED)
def checkout_config(order_id: Annotated[str, Query(pattern=ORDER_ID)]):
    from app.services.razorpay_client import client
    order = client.order.fetch(order_id)
    return {
        "key_id": settings.razorpay_key_id,
        "order_id": order["id"], "amount_paise": order["amount"], "currency": order["currency"],
        "checkout_note": "A fresh checkout requires an explicit payment by the customer; no automatic debit is performed.",
    }
