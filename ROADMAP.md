# RecoverAI: verified state and improvement plan

Reviewed 5 November 2026. This is a repository review, not a production readiness
certification. The available implementation uses Razorpay Test Mode and
synthetic ML data. The fresh `D:\RecoverAI` installation has verified test-mode
credentials, initialized database tables, and a completed provider-origin
failure-to-recovery flow. See [the test record](TEST_MODE_VERIFICATION.md).

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
- Open/unpaid attempts remain pending. Each execution stores its provider ID,
  action, amount, and currency. Delayed captures are checked against that exact
  execution, including earlier failed attempts, and can settle the original case.
  Old failures cannot advance a newer attempt; outcomes are unique per execution.
- Concurrent request, approval, observation, timeout, and persistence-failure
  regression tests. Total local suite including authentication coverage:
  286 passing tests including reviewed reconciliation, dashboard login, early-event replay, and attribution.
- A public webhook-only gateway excludes operator APIs, checkout, documentation,
  and configuration paths. Local HTTP checks cover valid/invalid signatures,
  processing a replay of an old failed test payment, and duplicate rejection
  without creating recovery actions. An actual provider-origin failed payment
  and captured recovery payment also reached the tunnel and were processed on
  4 November 2026; the original case became recovered with one success outcome.
- Grouped synthetic evaluation: 1,600 training contexts, 400 held-out contexts,
  zero overlap. Stored model/data hashes, baseline, probability-quality metrics,
  and calibration diagnostics in `ML/evaluation.json`.
- GitHub workflow for regression tests and evaluation reports. Check the latest
  Actions run for its actual remote result; a local pass is not a remote pass.

## Fix before a public deployment

### 1. Access control and input validation (implemented and tested)

Implemented: configured single-operator HTTP Basic protection, salted password
hashing, dashboard login/logout with session expiry, POST changes, bounded input
schemas, and explicit CORS/browser-origin restrictions. The protected same-origin
checkout loads order amount/currency and the public key ID from the backend;
credentials are not embedded in its source. Signed webhooks remain separate.

Unauthorized access and invalid inputs are covered by API tests. Dashboard tests
exercise hidden content, rejected login, successful login/logout, session expiry,
and credential rotation. A hosted Razorpay Test Mode checkout completed the
recovery flow; the protected local checkout and dashboard login still need their
own configured browser smoke test. This single-operator implementation
still needs HTTPS and external rate limiting before public deployment; future
multi-operator roles and identity-provider integration remain separate work.

### 2. Exact attribution and reviewed success reconciliation (implemented)

Implemented: `recovery_executions` binds each new automatic or approved action
to its provider resource. `execution_outcomes` gives each execution one result.
Order captures and paid links must match stored INR amounts; links must also
match the resource ID and full amount paid. A late success upgrades that
execution's failed result, settles the original case, clears its reservation,
and expires pending reviews. Newer executions' outcomes remain untouched.

Tests cover older order/link captures, duplicate event IDs and separate event
IDs for the same capture, repeated action types, old failure/pending events,
amount/currency mismatches, and late success during review or after closure.
Legacy audit records and outcomes are imported only when attribution is
unambiguous; uncertain history stays blocked for reconciliation.

Implemented next: verified events are stored in a minimal durable inbox before
processing. Recovery intents are saved before provider requests and referenced
in provider notes. Early captures, and early failures identified by that intent,
wait for execution persistence. A separate local worker reuses the same claims
and provider verification to replay them; it never starts a new independent case
for an identified early recovery failure. Tests cover pre-response events,
separate database sessions, competing workers, temporary read failures, and a
creation/lookup timing race.

The worker backs off, processes bounded batches, and retains unresolved events
for reconciliation after 20 attempts. Processing/reconciliation claims are not
forced. The D drive database was upgraded and the local gateway/worker smoke
tests passed. This upgrade was tested with simulated early events, not a new
provider-origin timing experiment.

Implemented: the authenticated Recovery Review tab lists blocked/in-progress
cases and held webhook events. Provider checks are explicit and read-only.
Verified existing executions, or an intent with matching provider notes, ID,
amount and currency, can settle a blocked case after a fresh provider check.
Settlement claims only `needs_reconciliation`, records the operator in audit,
and cannot create a new order/link or advance a failed/pending attempt. Lost
responses can be matched to an operator-supplied existing provider resource;
ambiguous action history stays blocked. Competing reconcilers settle once.

Remaining: processing claims are not reset here, since their owner may still be
running. Unknown legacy resources without intent metadata, ambiguous history,
exhausted webhook retries and unrelated captures still need investigation. Held
webhooks are shown read-only and are not forcibly replayed by settling a case.
Add an operational ownership/lease protocol before offering crash recovery for
processing claims; do not infer that an old timestamp means a process is dead.
Successful recovery stops local follow-up work, but does not automatically
cancel previously issued provider links/orders. Add supported provider cleanup
and reconciliation before promising protection from multiple payments.
Do not blindly expire claims or promise exactly-once external charges.

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

Recommended next implementation: exact execution/outcome attribution and
reconciliation, plus manual test-mode checkout verification after operator setup.
