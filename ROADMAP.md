# RecoverAI: verified state and improvement plan

Reviewed 7 November 2026. This is a repository review, not a production readiness
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
  374 passing local tests including matched policy evaluation, isolated demo reproducibility, dashboard evidence checks and existing recovery safeguards.
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

### 3. Review deadlines and approval policy (implemented); polling remains

Implemented: a bounded local deadline worker expires overdue reviews without
contacting the provider. Review status, failed-case closure, audit and review
claim cleanup commit together. Concurrent approvals and competing expiry
workers share the same case claims; processing/reconciliation/awaiting-outcome
claims are not taken over. Expiry at approval time uses the same closure path.
Recovered cases remain recovered, and a verified late capture can still settle
an expired case. The worker operates without an open dashboard while its
process is running; it does not register itself as an OS startup service.

Automatic and human decisions now use the same one-execution-per-action-type
rule. Pending/expired/actioned review recommendations do not consume retry
budgets or cooling-off time; executed retries do. `MAX_RETRY_ATTEMPTS` is an
upper bound, not a promise to execute that many retries under this policy.

Provider order/link requests now use the same exact Decimal-to-paise conversion
as stored execution expectations. Rs.19.90 becomes 1,990 paise; invalid or
fractional-paise amounts are rejected before a provider request.

Remaining: scheduled pending-outcome checks, reviewed crash recovery, provider
resource cleanup, and explicit fraud-stop/customer-opt-out rules. The worker
must be supervised/restarted for continuous operation.

## Make the ML and business story defensible

### 4. Matched synthetic policy benchmark (implemented)

The benchmark now uses unique grouped held-out contexts with a fixed potential
outcome for every action. Blanket retry, cause rules, ML value ranking and the
application's guarded ML selector share costs, hard guards and a one-action
budget. It no longer samples baseline outcomes from the evaluated model.
Five predefined split seeds and a paired primary-split bootstrap are reported;
selectors cannot read labels, and overlapping test sets are not pooled.

On seed 42, ML value ranking minus cause rules is Rs.-735.83, with a paired
interval [Rs.-12,971.92, Rs.13,456.14]. A clear ML advantage is not established.
Guarded-policy reviews remain unresolved; immediate automatic recovery cannot
be called full post-review performance. Prior-retry/cooling-off assumptions
and omitted reviewer costs are explicit. See `reports/POLICY_BENCHMARK.md`.

The dashboard uses fingerprint-verified recorded evidence and rejects stale
inputs/source. Legacy simulated uplift figures were removed from the main
README/dashboard. The old self-referential reporting helper is legacy only.
Real customer history and a merchant outcome pilot remain necessary before
making live performance claims.

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
- Implemented: a documented D drive Windows setup, private password reset,
  and separate local operator/webhook listeners.
- Implemented: six repeatable offline scenarios using a fake provider, fresh
  DB, network guard and recorded HTML/JSON/Markdown replay; no merchant reset.
  The former live_demo command now defaults to this safe offline runner.
- Add health/readiness checks, structured logs with sensitive-data redaction,
  worker failure visibility, and a documented deployment configuration.

### 7. Operator dashboard

- Show a case timeline with the exact action, provider result, and reason.
- Add date/status/cause filters, search, pagination, and useful empty states.
- Make pending, interrupted, expired, and recovered cases easy to distinguish.
- Implemented: authenticated review, reviewed reconciliation with operator
  audit, and a matched Policy Benchmark view with uncertainty/deferral limits.
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

Agreed prototype-evidence phase completed: matched benchmark, repeatable demo,
architecture, current setup and supported claims. Next agreed phase is interview
preparation using this implementation and its measured limitations. Production
hardening and a real merchant pilot remain separately scoped work.
