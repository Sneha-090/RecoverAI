# RecoverAI: verified state and improvement plan

Updated 10 November 2026. This is a repository review, not a production readiness
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
  604 passing local tests, including original-order ownership, persistent stops, isolated backup restore, bounded webhooks, authenticated checkout and exact approval-history attribution.
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
recovery flow, and the owner completed dashboard login. The fresh retry attempt
was verified failed after explicit cancellation, and its reviewed failure was returned to manual review without creating another checkout.
The separately approved alternate-method link visually excluded netbanking but
remains unpaid; a completed capture for these upgraded flows remains outstanding.
This single-operator implementation still needs HTTPS and external rate limiting before public deployment; future
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
and cannot create a new order/link. A separate reviewed-failure control can return
only freshly verified failed executions to explicit manual review; pending/paid
resources remain blocked. Lost
responses can be matched to an operator-supplied existing provider resource;
ambiguous action history stays blocked. Competing reconcilers settle once.

Remaining: processing claims are not reset here, since their owner may still be
running. Unknown legacy resources without intent metadata, ambiguous history,
exhausted webhook retries and unrelated captures still need investigation. Held
webhooks are shown read-only and are not forcibly replayed by settling a case.
Add an operational ownership/lease protocol before offering crash recovery for
processing claims; do not infer that an old timestamp means a process is dead.
Successful recovery stops local follow-up work, but does not automatically
cancel previously issued provider links/orders. Reviewed Test Mode cleanup now
verifies and cancels unpaid links belonging to closed cases; paid/partial links
and orders are excluded. This is not a guarantee against multiple payments.
Do not blindly expire claims or promise exactly-once external charges.

### 3. Review deadlines, approvals and pending-outcome polling (implemented)

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

Implemented: bounded pending-outcome polling uses the same case claims and
provider verification, and reviewed cleanup handles eligible old unpaid links.
Partial/inconsistent payments block further full-amount collection for
reconciliation. Provider connect/read timeouts are configured.
Implemented: persistent customer-opt-out, merchant-cancellation, fraud-concern and
operator-stop controls across known same-order attempts. These do not recall an
already shared link or constitute automatic fraud detection. Remaining: reviewed
crash recovery and worker job-progress monitoring. See OPERATIONS.md.

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

Current synthetic accuracy is 76.2%, ROC-AUC 0.759 versus 0.500 for the
constant-prior baseline, and recall at classification threshold 0.5 is 22.9%.
These are classification diagnostics, not the policy recovery rate.

Implemented: four predefined candidates are compared on inner grouped validation;
the selected regularized logistic model is refitted on outer training data.
Reports include per-action/per-cause metrics, calibration-bin sample counts and
training ranges. Unsupported causes and out-of-range numeric inputs require
manual assessment. The former probability-confidence band is replaced by an
explicit 2% near-tie net-value business review guard. Verified customer history
and exact non-identifying feature snapshots are recorded when available.

Remaining: real merchant calibration/validation, monitored drift and a complete
model-version lifecycle for historical decisions. Existing synthetic test sets
have already been inspected and cannot serve as a fresh blind merchant audit.

## Improve usability and reproducibility

### 6. Reliable setup and operations

- Implemented: hash-checked Python 3.13 dependency locks, frozen Alembic baseline,
  strict backed-up legacy adoption and internal readiness checks.
- Implemented: a documented D drive Windows setup, private password reset,
  and separate local operator/webhook listeners.
- Implemented: six repeatable offline scenarios using a fake provider, fresh
  DB, network guard and recorded HTML/JSON/Markdown replay; no merchant reset.
  The former live_demo command now defaults to this safe offline runner.
- Implemented: one-command private Test Mode supervision, process status,
  restart budgets and shutdown of owned process trees. Worker job-progress
  heartbeats, centralized alerts, log retention and hosted deployment remain open.

### 7. Operator dashboard

- Implemented: readable event timelines, recorded action/reason/provider references,
  literal payment-ID search, status filtering, bounded results and empty states.
- Implemented: cause-filtered action distributions distinguish first decisions,
  executed actions and human approvals, with explicit source/sample counts.
- Additional date filters and pagination remain optional usability work.
- Implemented: authenticated review, reviewed reconciliation with operator
  audit, and a matched Policy Benchmark view with uncertainty/deferral limits.
- Implemented: source-separated Test Mode/synthetic totals, matched cost-adjusted
  policy evidence and benchmark JSON download.

## Useful additions after the core gaps

- Consent-aware email or WhatsApp recovery reminders with delivery tracking.
- Implemented: alternate-method links hide the failed method and verify captured
  method; retries open a fresh explicit checkout. Merchant-enabled methods vary.
- A deployed customer-facing portal remains separate from the private operator
  Test Mode checkout.
- Merchant-specific policy settings and, later, isolated merchant workspaces.
- A short demo video, architecture diagram, and interview walkthrough showing
  duplicate delivery, human review, pending payment, and verified recovery.

## Active direction: prepare a supervised single-merchant pilot

Continue hardening the product rather than freezing feature development. The first
recommended segment is a small online-course/adult skill-training business with
one-time INR fees. See [pilot plan](PILOT_PLAN.md) for the scope, acceptance gates
and measurements. No real merchant or approved live dataset is available yet.

Next work in order:

- [x] Bind known original provider orders to one permanent recovery owner; stop on
  verified original-order success and exclude it from recovered revenue.
- [x] Persist operator opt-out/cancellation/fraud stops across same-order attempts.
- [x] Restore an actual backup into an isolated upgraded copy with record checks.
- [x] Verify fresh failed retry, explicit failure-to-review and separate alternate
  approval. Show only the actual approved action and its exact audit resource.
- [ ] Complete a fresh successful hosted retry and alternate-method capture. The
  latest alternate-method link remains unpaid; no new capture is claimed.
- [ ] Add merchant-approved invoice mapping across distinct original orders and
  agreed consent/refund/dispute workflows.
- [ ] Add job-progress monitoring, deployment alerts and hosted recovery procedures.
- [ ] Select a willing merchant, validate the need and agree on a supervised pilot.
- [ ] Deploy with reviewed HTTPS, access controls, operational ownership and budget.

Dependency locks, migration/readiness and the local supervisor are concrete
hardening steps. They do not establish production readiness or live recovery uplift.
Only Test Mode data is available; synthetic evidence remains labeled throughout.

## Resume claims supported today

Describe a tested **Razorpay Test Mode payment-recovery application** combining
FastAPI, SQLAlchemy, Streamlit, logistic regression, deterministic policies, and
database-backed duplicate prevention. Cite the grouped synthetic benchmark and
its limitations. Do not describe synthetic revenue as merchant revenue, a test
checkout as a production deployment, or probabilistic predictions as guaranteed
recovery.

The matched benchmark and repeatable demo remain useful evidence. Current work
continues toward a supervised merchant pilot; interview preparation can use the
verified implementation while these remaining product gaps are closed.
