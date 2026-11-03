# RecoverAI: verified state and improvement plan

Reviewed 3 November 2026. This is a repository review, not a production readiness
certification. The available implementation uses Razorpay Test Mode and
synthetic ML data. A fresh `D:\RecoverAI` installation was started separately;
its credentials, database initialization, and live checkout have not yet been
verified in this review.

## Implemented and tested

- FastAPI payment ingestion, deterministic diagnosis, probability prediction,
  expected-value scoring, human escalation, and execution services.
- Streamlit views for test-mode cases, review, explanations, audit history,
  synthetic simulations, and impact.
- Case-wide checks stop successful, closed, and expired cases before recovery;
  re-fetching an original charge preserves recovery status and original age.
- Database-backed webhook claims and per-payment reservations prevent competing
  requests from starting overlapping operations. Interrupted operations remain
  blocked for reconciliation rather than automatically repeating a provider call.
- Open/unpaid attempts remain pending. A mismatched old event cannot advance the
  current attempt. This is protection against advancing the wrong attempt, not
  complete historical outcome attribution.
- Concurrent request, approval, observation, timeout, and persistence-failure
  regression tests. Total local suite: 138 passing tests as of this review.
- Grouped synthetic evaluation: 1,600 training contexts, 400 held-out contexts,
  zero overlap. Stored model/data hashes, baseline, probability-quality metrics,
  and calibration diagnostics in `ML/evaluation.json`.
- GitHub workflow for regression tests and evaluation reports. Check the latest
  Actions run for its actual remote result; a local pass is not a remote pass.

## Fix before a public deployment

### 1. Access control and input validation

Evidence: `app/main.py` exposes `/create-order`, `/process-payment`, and payment
lookup without authentication; state-changing routes use GET and CORS allows
every origin. `dashboard.py` exposes approvals without an application login.

Implement authenticated operator access, authorization on payment operations,
POST requests for changes, bounded request fields, and explicit allowed origins.
Update `scripts/checkout.html` with the changed routes. Browser code must not
contain a shared operator/backend secret. Keep signed webhook verification as a
separate provider authentication mechanism.

Done when unauthorized calls cannot create or process payment actions, invalid
amounts/IDs are rejected before provider calls, and the checkout demo still works.

### 2. Exact attribution and reconciliation

Evidence: `app/services/execution.py` still obtains the latest execution from
audit JSON; `Outcome` associates results with payment/action type, not a unique
execution. An old order's delayed capture is ignored when a newer action exists.
A provider event arriving before the execution audit is stored can be unmatched.

Introduce a persisted execution identity with indexed provider IDs and unique
outcomes per execution. Match events to that execution, verify amount/currency,
recognize success from an earlier attempt, and stop outstanding recovery work.
Provide reviewed reconciliation for ambiguous timeouts and interrupted claims.
Do not blindly expire claims or promise exactly-once external charges.

Done when out-of-order, duplicate, and early-arriving events are covered by
integration tests and a verified late success updates the original case once.

### 3. Complete review and retry lifecycle

Evidence: `app/services/escalation.py` defines review expiry but no background
scheduler invokes it. Expired reviews can leave waiting reservations. Automatic
scoring excludes an action type once executed, so the configurable three-retry
limit does not currently imply three actual retries. Human approval does not
reject every previously tried action.

Schedule expiry and pending-outcome checks; clean up claims through explicit
state transitions. Define whether a case permits one retry or multiple governed
attempts, and apply the same policy to human selections. Add fraud-stop and
customer-opt-out checks.

Done when policy settings match actual behavior, timeout handling works without
an open dashboard, and an approval cannot bypass limits or repeat settled work.

## Make the ML and business story defensible

### 4. Independent policy benchmark

Evidence: `scripts/run_batch_simulation.py` samples action-level rows and uses a
fixed 25% stand-in for unobserved actions. `app/services/reporting.py` evaluates
blanket retry using the model's own probabilities. These use different outcome
assumptions and do not establish real business uplift. Live ingestion does not
populate the customer history consumed by the model.

Benchmark unique held-out contexts under the same simulator and attempt budget.
Compare blanket retry, a cause-based rules policy, and model-based selection.
Report net recovered amount after costs, recovery rate, number of interventions,
and uncertainty over multiple seeds. Keep live, synthetic, and historical
screenshots visibly separate. Connect anonymized customer history and validate
on real outcomes before making merchant performance claims.

### 5. Probability quality and model lifecycle

Current synthetic ROC-AUC is 0.761, compared with 0.500 for the constant-prior
baseline. Recall at the fixed 0.5 classification threshold is only 23.8%.
Calibration diagnostics exist, but the model has not been recalibrated.

Use a separate grouped validation partition for threshold/calibration choices,
reserve the test partition for final evaluation, measure performance by cause
and amount, and record model versions with each decision. Detect unfamiliar
inputs and drift; define a conservative fallback when predictions are unavailable.

## Improve usability and reproducibility

### 6. Reliable setup and operations

- Add tested dependency locks and database migrations for future schema changes.
- Document a clean Windows setup, `.env` creation without exposing secrets,
  test-mode checkout, and troubleshooting for OneDrive/low disk space.
- Add a repeatable demo seed/reset procedure that cannot erase merchant data.
- Add health/readiness checks, structured logs with sensitive-data redaction,
  worker failure visibility, and a documented deployment configuration.

### 7. Operator dashboard

- Show a case timeline with the exact action, provider result, and reason.
- Add date/status/cause filters, search, pagination, and useful empty states.
- Make pending, interrupted, expired, and recovered cases easy to distinguish.
- Add authenticated review, rejection reasons, reviewer identity, and reviewed
  reconciliation controls. Render guardrail status from real checks.
- Add clearly labeled synthetic/live metrics, cost-adjusted reports, and export.

## Useful additions after the core gaps

- Consent-aware email or WhatsApp recovery reminders with delivery tracking.
- A customer recovery page that offers genuinely distinct payment methods;
  currently `payment_link` and `alt_method` both create payment links.
- Merchant-specific policy settings and, later, isolated merchant workspaces.
- A short demo video, architecture diagram, and interview walkthrough showing
  duplicate delivery, human review, pending payment, and verified recovery.

## Resume claims supported today

Describe a tested **Razorpay test-mode revenue recovery prototype** combining
FastAPI, SQLAlchemy, Streamlit, logistic regression, deterministic policies, and
database-backed duplicate prevention. Cite the grouped synthetic benchmark and
its limitations. Do not describe synthetic revenue as merchant revenue, a test
checkout as a production deployment, or probabilistic predictions as guaranteed
recovery.

Recommended next implementation: access control and validated POST endpoints,
then exact execution/outcome attribution and reconciliation.
