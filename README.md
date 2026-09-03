# RecoverAI — AI-Assisted Revenue Recovery Agent

RecoverAI is an AI-assisted revenue recovery system for failed Razorpay payments.

Instead of treating every failed payment with the same retry strategy, RecoverAI:

- Detects failed payments through Razorpay webhooks
- Diagnoses the likely failure cause
- Uses ML predictions to estimate recovery probability
- Applies eligibility rules and business guardrails
- Scores available recovery actions
- Automatically executes selected low-risk actions
- Escalates selected cases for human approval
- Verifies real Razorpay recovery outcomes
- Records decisions and outcomes for auditability

> **Goal:** Recover more payment revenue while avoiding unnecessary retries and unsafe automated actions.

---

## Problem

Payment failures create direct revenue leakage.

Not every failed payment should be handled in the same way:

- Some failures are worth retrying
- Some are better handled using a payment link
- Some may need an alternate payment method
- High-value or uncertain cases may require human approval

RecoverAI approaches payment recovery as a **decision problem**, rather than simply retrying every failed payment.

---

## How RecoverAI Works

```text
Razorpay Payment
       |
       | payment.failed
       v
Razorpay Webhook
       |
       v
Payment Ingestion
       |
       v
Failure Diagnosis
       |
       v
ML Recovery Prediction
       |
       v
Eligibility + Guardrails
       |
       v
Cost-Aware Action Scoring
       |
       v
Decision
  /       |       \
AUTO   HUMAN      SKIP
  |     REVIEW
  v
Recovery Action
       |
       v
Razorpay Recovery Order
       |
       v
Customer Retry
       |
       | payment.captured
       v
Outcome Verification
       |
       v
Recovered / Next Action / Closed
```

---

## Recovery Actions

RecoverAI currently supports three recovery actions:

- `retry`
- `payment_link`
- `alt_method`

The final decision can be:

- **Auto** — execute the selected recovery action automatically
- **Human Review** — require business-user approval
- **Skip** — do not attempt recovery

---

## Live Razorpay Integration

RecoverAI uses Razorpay Test Mode to demonstrate a real payment recovery workflow.

### Failed Payment Flow

```text
Customer Payment Attempt
        |
        v
Payment Fails
        |
        v
Razorpay sends payment.failed
        |
        v
RecoverAI Webhook
        |
        v
Payment Ingestion
        |
        v
Diagnosis + ML Prediction
        |
        v
Eligibility + Guardrails
        |
        v
Decision
        |
        v
Recovery Action
```

The webhook validates Razorpay's webhook signature before processing the event.

RecoverAI also includes a re-entry guard to reduce duplicate recovery actions when a recently processed failed-payment webhook is delivered again.

---

## Live Recovery Verification

The current prototype demonstrates the complete closed-loop recovery flow for the **retry** strategy:

```text
Original Payment
       |
       v
FAILED
       |
       v
payment.failed webhook
       |
       v
RecoverAI decides retry
       |
       v
RecoverAI creates Recovery Order
       |
       v
Customer completes retry payment
       |
       v
payment.captured webhook
       |
       v
RecoverAI verifies the real Razorpay state
       |
       v
Original Case = RECOVERED
```

This allows RecoverAI to verify an actual recovery outcome instead of assuming that creating a recovery order means the payment succeeded.

---

## Dashboard

RecoverAI provides a Streamlit dashboard with the following sections.

### Live Razorpay Cases

Displays real Razorpay Test Mode payment cases including:

- Payment ID
- Amount
- Diagnosed cause
- Actions attempted
- Decision type
- Latest outcome
- Final status

For retry-based recoveries, the dashboard provides a **Retry Payment** link for the generated recovery order.

### Batch Evaluation

Evaluates the recovery decision logic against synthetic payment data and displays:

- Total cases
- Recovered cases
- Recovery rate

### Human Review

Allows a business user to:

- Inspect the ML recommendation
- Understand why a case was escalated
- Choose a recovery action
- Approve and execute the action

### Guardrails

Displays safety policies such as:

- Maximum retry attempts
- Retry cooling-off period
- Maximum recovery window
- Human-review confidence band
- High-value review threshold
- Approval deadline
- Non-retryable Razorpay states
- Duplicate-attempt prevention

### Impact

Compares RecoverAI's recovery metrics against a naive blanket-retry baseline using the project's synthetic evaluation data.

### Decision Explanation

Shows case-level information including:

- Diagnosis
- ML probabilities
- Recovery scores
- Selected action
- Decision type
- Decision reason
- Observed outcomes
- Final payment status

---

## Technology Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- SQLite

### Payments

- Razorpay Test Mode
- Razorpay Webhooks

### AI / ML

- scikit-learn
- pandas
- NumPy
- joblib
- Logistic Regression

### Dashboard

- Streamlit

### Testing

- pytest

### Local Webhook Development

- ngrok

---

## Project Structure

```text
RecoverAI_Project/
│
├── app/
│   ├── api/
│   │   └── webhooks.py
│   ├── db/
│   ├── models/
│   └── services/
│       ├── diagnosis.py
│       ├── decision.py
│       ├── eligibility.py
│       ├── execution.py
│       ├── ingestion.py
│       ├── ml_service.py
│       ├── order_service.py
│       └── razorpay_client.py
│
├── ML/
│   └── recovery_model.joblib
│
├── scripts/
│   └── checkout.html
│
├── tests/
│
├── dashboard.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Sneha-090/RecoverAI.git
cd RecoverAI
```

### 2. Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file using `.env.example` as a template.

```env
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=

DATABASE_URL=sqlite:///./recoverai.db

HUMAN_REVIEW_TIMEOUT_HOURS=24
MAX_RECOVERY_WINDOW_DAYS=14
```

Never commit real API credentials or webhook secrets.

---

## Running the Project

### Start FastAPI

```bash
uvicorn app.main:app --reload
```

FastAPI runs on:

```text
http://127.0.0.1:8000
```

### Start ngrok

In another terminal:

```bash
ngrok http 8000
```

Use the HTTPS ngrok URL for the Razorpay webhook endpoint:

```text
https://YOUR-NGROK-URL/webhooks/razorpay
```

### Start the dashboard

In another terminal:

```bash
streamlit run dashboard.py
```

### Start the local checkout page

The current demo uses the existing local checkout page:

```text
http://127.0.0.1:5500/scripts/checkout.html
```

The dashboard's retry link opens the generated recovery Order through this checkout page.

---

## Webhook Events

The current webhook integration handles:

```text
payment.failed
payment.captured
```

Webhook endpoint:

```text
POST /webhooks/razorpay
```

Before processing, RecoverAI verifies the Razorpay webhook signature using the configured webhook secret.

---

## Demo Flow

A typical live demonstration is:

1. Create a Razorpay Test Mode order
2. Open the test checkout
3. Intentionally fail the payment
4. Razorpay sends `payment.failed`
5. RecoverAI receives the webhook
6. Diagnose the failure
7. Generate ML recovery probabilities
8. Apply eligibility and guardrails
9. Select a recovery action
10. RecoverAI creates a recovery order
11. Open the retry payment checkout
12. Complete the recovery payment successfully
13. Razorpay sends `payment.captured`
14. RecoverAI verifies the real recovery state
15. Dashboard shows the case as recovered

---

## Testing

Run the complete test suite with:

```bash
python -m pytest -q
```

Current test suite:

```text
29 tests passing
```

The tests cover areas including:

- Diagnosis logic
- Eligibility rules
- Decision scoring
- Decision persistence
- Escalation and timeout behaviour
- Synthetic-data sanity checks

---

## AI / ML Approach

The current prototype uses Logistic Regression to estimate recovery probability for candidate recovery actions.

The model is trained on synthetic data designed to demonstrate the recovery decision architecture.

The ML prediction is one component of the decision process rather than the sole decision-maker.

The final decision combines:

```text
ML Probability
      +
Eligibility
      +
Business Guardrails
      +
Recovery Cost
      +
Action Scoring
      +
Human-Review Policy
```

The model can later be retrained and calibrated using real merchant payment and recovery history.

---

## Safety and Guardrails

RecoverAI includes safeguards such as:

- Retry eligibility checks
- Maximum retry attempts
- Retry cooling-off periods
- Maximum recovery window
- Human-review thresholds
- High-value escalation
- Approval deadlines
- Non-retryable Razorpay states
- Duplicate-attempt prevention
- Webhook signature verification

Fraud-flag automation is intentionally marked as not implemented in the current prototype.

---

## Current Limitations

This is a hackathon prototype, not a production payment-recovery system.

### ML Data

The current ML model is trained on synthetic data rather than real merchant recovery history.

Its predictions should therefore be treated as an architectural demonstration, not production-grade prediction accuracy.

### Outcome Verification

The current live closed-loop outcome verification is demonstrated end-to-end for the `retry` recovery path.

`payment_link` and `alt_method` actions are implemented, but their automatic outcome closure is not currently connected to the same live captured-payment verification flow.

Human-approved recovery execution is implemented, while automatic outcome closure for those recovery actions remains a future extension.

### Infrastructure

The current demo uses:

- SQLite
- Local FastAPI
- ngrok
- Local checkout hosting
- Streamlit

A production deployment would use managed infrastructure, stronger event-level idempotency, persistent event tracking, authentication/authorization, and production-grade observability.

---

## Why RecoverAI?

Many payment demos stop at:

```text
Payment Failed
      |
      v
Retry Payment
```

RecoverAI focuses on the decision problem after a payment fails:

```text
Payment Failed
      |
      v
Why did it fail?
      |
      v
Is recovery worth attempting?
      |
      v
Which action has the best expected recovery value?
      |
      v
Should AI act automatically or ask a human?
      |
      v
Did the recovery actually work?
      |
      v
How much revenue was recovered?
```

The goal is not simply to retry payments.

It is to make recovery decisions:

- measurable
- explainable
- controlled
- outcome-aware

---

## Future Improvements

Potential future extensions include:

- Real merchant recovery datasets
- Event-ID based webhook idempotency
- Complete payment-link outcome verification
- Automatic outcome closure for human-approved recoveries
- Recovery-failure re-scoring linked to the original case
- Stronger observability and alerting
- Managed database infrastructure
- Production authentication and authorization
- Improved model calibration and evaluation

---

## Author

**Sneha Dubey**

GitHub:

https://github.com/Sneha-090/RecoverAI