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
- Re-scores remaining recovery options after a failed recovery attempt
- Records decisions, actions, outcomes, and webhook events for auditability

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
AUTO    HUMAN      SKIP
        REVIEW
  |        |
  v        v
Recovery Action
       |
       v
Razorpay Recovery Order / Payment Link
       |
       v
Customer Retry / Payment
       |
       | payment.captured / recovery failure
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

The system re-evaluates remaining eligible actions after an unsuccessful recovery attempt while excluding actions that have already been tried.

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

RecoverAI also uses Razorpay's event ID to prevent duplicate webhook processing. Processed webhook event IDs are stored in the audit log and protected by a database uniqueness constraint.

---

## Webhook Reliability and Idempotency

RecoverAI handles:

```text
payment.failed
payment.captured
```

Each incoming webhook is checked using the Razorpay event ID:

```text
X-Razorpay-Event-Id
        |
        v
Duplicate Event Check
        |
   +----+----+
   |         |
 New       Duplicate
   |         |
   v         v
Process    Ignore
```

This prevents the same Razorpay event from triggering duplicate recovery processing.

The webhook endpoint also retains additional payment/action-level safeguards for recently processed recovery attempts.

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

Payment-link and alternate-method recovery actions are implemented in the recovery layer, including outcome-verification logic. The primary live demonstration focuses on the retry path because it is the most directly demonstrated Razorpay Test Mode flow.

---

## Dashboard

RecoverAI provides a Streamlit dashboard with the following sections.

### Top-Level Recovery Snapshot

The dashboard displays a top-level synthetic impact snapshot containing:

- Payments in simulation
- Recovered payments
- Revenue recovered

The snapshot is clearly labeled as synthetic evaluation data. Live Razorpay payment cases are shown separately.

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

The batch evaluation uses real decision logic while the simulated outcomes are explicitly identified as synthetic.

### Human Review

Allows a business user to:

- Inspect the ML recommendation
- Understand why a case was escalated
- Choose a recovery action
- Approve and execute the action

Human-approved actions are recorded and included in recovery outcome tracking.

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

The dashboard shows:

- Total recovered revenue
- Recovery rate
- Difference versus baseline
- Recovery-rate comparison chart

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

Payments can be selected from a dropdown for easier live demonstration.

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
uvicorn app.main:app --reload --port 8000
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

Configure the webhook in Razorpay Test Mode for:

```text
payment.failed
payment.captured
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

To serve the project directory locally, run from the project root:

```bash
python -m http.server 5500
```

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

Webhook event IDs are stored for idempotency and duplicate events are ignored.

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
15. Dashboard shows the original case as recovered

---

## Testing

Run the complete test suite with:

```bash
python -m pytest -q
```

Current test suite:

```text
45 tests passing
```

The tests cover areas including:

- Diagnosis logic
- Eligibility rules
- Decision scoring
- Decision persistence
- Recovery execution
- Recovery outcome verification
- Escalation and timeout behaviour
- Webhook signature verification
- Webhook recovery-case linking
- Webhook event idempotency
- Payment-link recovery tracking
- Synthetic-data sanity checks

The test suite currently reports deprecation/joblib warnings in addition to the passing test results.

---

## AI / ML Approach

The current prototype uses Logistic Regression to estimate recovery probability for candidate recovery actions.

The model is trained on synthetic data designed to demonstrate the recovery decision architecture.

The current training dataset contains:

```text
2,000 payment contexts
×
3 candidate actions
=
6,000 action-level records
```

For each payment context, the training data represents:

- `retry`
- `payment_link`
- `alt_method`

The training features include:

```text
amount
cause
attempts
days_since_failure
past_rate
action_type
cause_action
```

The `cause_action` feature captures the relationship between a failure cause and a particular recovery action.

The synthetic customer-history generation is used to derive `past_rate` from simulated historical failures and recoveries.

### Model Evaluation

The model is evaluated using classification metrics and threshold analysis.

A recent training run produced approximately:

```text
Accuracy  : 76.6%
Precision : 61.3%
Recall    : 24.6%
F1 Score  : 35.1%
```

These figures are based on the project's synthetic evaluation data and should not be interpreted as production accuracy.

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

The model can later be retrained and recalibrated using real merchant payment and recovery history.

---

## Safety and Guardrails

RecoverAI includes safeguards such as:

- Retry eligibility checks
- Maximum retry attempts
- Retry cooling-off periods
- Maximum recovery window
- Human-review confidence band
- High-value escalation
- Approval deadlines
- Non-retryable Razorpay states
- Duplicate-attempt prevention
- Webhook signature verification
- Webhook event-id idempotency

Fraud-flag automation is intentionally marked as not implemented in the current prototype.

---

## Current Limitations

This is a hackathon prototype, not a production payment-recovery system.

### ML Data

The current ML model is trained on synthetic data rather than real merchant recovery history.

Its predictions should therefore be treated as an architectural demonstration, not production-grade prediction accuracy.

### Recovery Verification

The current live closed-loop outcome verification is demonstrated end-to-end for the `retry` recovery path.

Payment-link and alternate-method actions are implemented in the recovery layer, including outcome-verification logic, but the primary live Razorpay demonstration focuses on the retry path.

### Infrastructure

The current demo uses:

- SQLite
- Local FastAPI
- ngrok
- Local checkout hosting
- Streamlit

A production deployment would use managed infrastructure, stronger database/event processing infrastructure, persistent observability, authentication/authorization, and production-grade monitoring.

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
- Production-grade model calibration and monitoring
- Stronger observability and alerting
- Managed database infrastructure
- Production authentication and authorization
- More robust payment-link outcome correlation
- Production-scale event processing and retry infrastructure
- Merchant-specific recovery policies
- Larger real-world evaluation datasets

---

## Author

**Sneha Dubey**

GitHub:

https://github.com/Sneha-090/RecoverAI