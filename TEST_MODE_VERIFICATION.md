# Razorpay Test Mode verification

Verified 4 November 2026 against the local `D:\RecoverAI` installation at
commit `056f3ff`. No real funds were charged. Checkout used published Razorpay
test cards, a dummy contact number, and the provider's demo bank controls.
Card storage was declined in both browser and checkout prompts.

## Observed failure-to-recovery flow

| Step | Evidence |
| --- | --- |
| Original payment | `pay_TwBUS2NXWHA8Cf`, INR 499, provider status `failed` |
| Provider failure webhook | `TwBYJMFQN7nJrQ`, local receipt `processed` |
| Automatic decision | One `payment_link` action; decision type `auto` |
| Generated recovery link | `plink_TwBYO5f3Mutwmy` |
| Recovery payment | `pay_TwBccMGKV92WQl`, provider status `captured` |
| Provider capture webhook | `TwBdSy7jmsjTgV`, local receipt `processed` |
| Recovery link after payment | Provider status `paid`, amount paid 49,900 paise |
| Original case after capture | Local status `recovered` |
| Stored result | Exactly one action and one `success` outcome for this case |
| Reservation after capture | No outstanding recovery reservation for this case |

The failure was processed at 17:45:27 UTC and recovery at 17:50:17 UTC.
These are actual provider-origin events, distinct from the earlier locally
signed replay events whose IDs start with `recoverai_*smoke`.

Only the signature-protected webhook gateway on localhost port 8002 was
exposed through the owner-approved ngrok endpoint. Operator APIs were excluded.
Credentials, raw webhook bodies, contact details, and database files are not
included in this record.

## Scope and remaining checks

This verifies one hosted card checkout and automatic payment-link recovery in
Test Mode. It does not establish production readiness, real-money recovery
performance, concurrent delivery behavior, or handling of every payment method.
The existing regression suite covers duplicates and competing operations; this
particular provider checkout was not a provider-redelivery experiment.

## Execution attribution upgrade

The subsequent upgrade adds persisted execution identities, one attributed
outcome per execution, exact historical matching, and amount/currency checks.
Regression tests simulate delayed provider captures and signed webhook
deliveries; those tests are separate from the actual provider checkout above.
They do not establish that a delayed provider event has been exercised remotely.

The additive schema initialization was run against `D:\RecoverAI`. Both new
tables were present afterward, and the case above remained `recovered` with
one action and one success outcome. Existing records were not deleted.

The next upgrade adds the minimal verified-event inbox, pre-request intent
references, and a bounded replay worker. The 251-test local suite covers early
capture/failure events, competing workers and retry exhaustion. On 5 November,
`recovery_intents` and `webhook_inbox` were added to the D drive database; the
existing recovered case still had one action and one success outcome. The
worker list/batch commands passed, the updated gateway accepted a signed
unsupported connection-check event with HTTP 200, and checkout/docs/config
paths remained HTTP 404. Gateway and worker were started locally. These smoke
checks do not establish a fresh provider-origin early-delivery experiment.

C drive ran out of space during this upgrade. Active implementation, test
artifacts and commits were continued in `D:\RecoverAI`; the old C drive working
copy was not synchronized afterward. No personal files were removed.

Next priorities remain reviewed reconciliation of interrupted operations,
provider resource cleanup, and scheduled review expiry.
The protected local checkout and dashboard login also need a separate browser
smoke test with operator login.


## Reviewed reconciliation upgrade — 5 November 2026

The local suite now has 286 passing tests. Reconciliation tests use simulated
provider responses, including successful/failed/pending outcomes, lost creation
responses, mismatched evidence, provider errors, concurrent operators and
rollback of an unsettled binding. Streamlit AppTest covers login protection,
explicit status checking, separate settlement, active-operation guards,
sanitized errors, stale-preview rejection and read-only held-event display.

The authenticated dashboard was started locally from `D:\RecoverAI` on
`http://127.0.0.1:8501`. Existing local data was not replaced with demo cases.
This verification does not claim a new provider-origin reconciliation exercise.


## Deadline maintenance and amount correctness — 6 November 2026

Local regression tests cover atomic review expiry, exact deadline boundaries,
rollback, competing workers, expiry/approval races and late successful capture
after expiry. Approval tests cover repeated-action rejection and executed-only
retry counting. Exact-money tests reproduce and fix the binary-float conversion
of Rs.19.90 to 1,989 rather than 1,990 paise. These tests use mocked provider
responses; this upgrade does not claim a new provider-origin payment exercise.

A local maintenance batch completed with zero overdue reviews. The previously
verified test case remained recovered. The deadline worker was started from
`D:\RecoverAI` in watch mode; it runs only while its process is active.

The final combined local suite passed all 350 tests. No new provider resources
were created by the maintenance or exact-money regression tests.


## Matched benchmark and repeatable demo — 7 November 2026

The combined local suite passed 374 tests. The new benchmark uses five fixed
context-group splits, identical synthetic outcomes/costs and one intervention
per context. The primary ML value-versus-rules net interval crosses zero;
ML superiority is not established. Deferred reviews are not assumed recovered.
Generated JSON/CSV/Markdown record the assumptions, decisions and fingerprints.

The offline runner passed six scenarios and reproduced identical recorded
results in two fresh processes, including the legacy live_demo alias. Tests
verify a pre-existing merchant fixture DB and `.env` stay unchanged. Every run
uses a new SQLite file and fake SDK provider; external networking is blocked
with local loopback IPC allowed for Windows asyncio. These results are not a
new provider-origin payment test. The actual D drive DB was not seeded with
these demo cases.

The dashboard's previous self-referential uplift comparison was replaced by
recorded matched evidence with stale-artifact checks. Streamlit AppTest verifies
its behavior, uncertainty text and legacy-baseline exclusion. The self-contained
HTML replay is generated and unit-checked; an attempted visual browser preview
could not start because the computer-control runtime was unavailable. No visual
browser QA success is claimed.

GitHub Actions run 42365122519 completed successfully for code/dashboard commit
17ed1b9, including regression tests, classifier evaluation, matched benchmark
and offline demo reproduction. Later documentation commits have their own
head-specific CI result; local success is not substituted for that result.


## 7 November sequential upgrade verification

Earlier on 7 November, a second manual hosted Test Mode walkthrough was verified:
INR 499 failed, RecoverAI created one recovery link, the replacement payment was
captured, and the original case became recovered with exactly one success
outcome. This preceded the latest diagnosis/coverage changes. Its historical
automatic decision is not a promise that a new generic failure will auto-execute:
`payment_failed` now requires manual assessment.

After the upgrades, the existing local Test Mode records contain three cases,
two recovered cases and INR 998 recorded recovery amount. No synthetic demo cases
were inserted into that database and no real merchant revenue is represented.

A separate unpaid INR 100 provider API capability probe confirmed that Razorpay
Test Mode accepts the alternate-method link request with card hidden, partial
payments disabled, SMS/email notifications off and reminders off. Its intent
notes preserved the excluded method. The newly created probe was fetched,
verified unpaid and cancelled (`plink_TxMNrlVWi6c3sI`); no payment was attempted.
This establishes API acceptance and cancellation, not hosted visual verification
or a completed alternate-method customer payment.

The updated local regression suite passed **477 tests** at code/test commit
`df55cc4`. The six isolated offline scenarios passed with the selected model,
coverage guards, recorded history features and refreshed source fingerprints.
The model was selected on inner grouped validation and remains synthetic-only;
its evaluation and matched policy benchmark still do not establish a clear
merchant benefit. Reports preserve the limits and exact source/data provenance.

The private API and dashboard responded successfully after restart, the approved
public webhook accepted a signed harmless connection check, and public `/docs`,
`/checkout` and `/.env` remained unavailable (404). The new pending-outcome worker
started with no due live cases and no errors. New reviewed cleanup controls were
checked with isolated provider doubles, including response loss, partial/paid
links and active-case restrictions. Fresh hosted visual tests of each upgraded
checkout flow remain separate; no browser-automation success is claimed.

Only Test Mode/synthetic data is available, as confirmed by the owner. Real
merchant validation remains out of scope until approved anonymised outcomes
exist; see [the validation plan](data/MERCHANT_DATA_GUIDE.md). GitHub CI is checked
per final commit; this local test count is not substituted for the cloud result.


## 9–10 November hardening and fresh walkthrough

The local database was upgraded through Alembic 0003 after verified backups,
retaining the three prior cases and both historically recovered Test Mode cases.
An actual backup was restored into a unique isolated copy, upgraded and checked
for integrity, references, preservation of original records and unchanged source.
No configured merchant database was overwritten by the restore drill.

New regressions cover permanent original-order ownership, competing same-order
attempts, original-checkout success without recovery credit, duplicate/partial
payments, persistent operator stops, order-level totals, Test-only provider
transport and the 256 KiB raw webhook limit. The authenticated dashboard checkout
uses the existing operator session while the independent API stays protected.

A fresh INR 499 original Test order (`order_Ty6BG6pNV8yply`) was attempted.
The embedded in-app browser did not open the mock netbanking popup. Explicit
cancellation produced provider-verified failed payment `pay_Ty6QWwHiy3qICK`.
The signed failure was processed and `customer_cancelled` required manual
assessment, without an automatic ML recommendation. Explicit operator approval
created retry order `order_Ty6X9VN9KGm2YU`. Its attempted payment
`pay_Ty6a8tlq2muz2c` was also explicitly cancelled and verified failed.
Neither attempt is a successful capture.

The case was held for reconciliation. Its initial blocking reason was not
persisted; a particular timeout cause is not established. The new reviewed-failure
control freshly checked the original and existing execution, recorded the failed
retry outcome and returned the case to manual review without creating a resource.
A separate explicit approval selected `alt_method`, creating
`plink_Ty6mI38swZvUFp` with the failed netbanking method excluded. The hosted page
visibly offered Cards and Wallet, with netbanking absent. This establishes visual
method exclusion, not a completed alternate-method payment or UPI availability.

At an earlier 10 November checkpoint, an SDK read showed the link `created`, INR 499 due
and zero paid. Both original/retry orders were `attempted`, zero paid. The local
case was held in `needs_reconciliation`; no claim was forced or new resource
created to bypass that state. At that checkpoint there were four local cases,
two recovered cases and INR 998 Test Mode recovery; the new case was not yet
recovered. Browser automation was unavailable due to a runtime ownership
error; an earlier native Cards click was rejected by automatic approval review
because the target was the ChatGPT window rather than an identified checkout.
No browser-payment success is claimed.

Approval history now displays the executed override (`retry`/`alt_method`) and
its exact bound audit rather than the original `manual_assessment` recommendation
or the most recent unrelated resource. An authenticated AppTest covers two
approvals on one case and an unbound legacy action.

The final local regression suite passed **604 tests** on 10 November. GitHub
Actions passed for `3a1c6c8` (run 42633939575); later commits have separate results.
After finding the prior local supervisor stopped, the six private services were
restarted from D drive. API readiness and dashboard health returned 200, anonymous
checkout 401, and gateway docs/checkout/config/readiness paths 404. The removed
experimental checkout-result route returned 404. Worker checks report process
liveness, not completed-job heartbeats. These local checks do not establish a
hosted deployment, live collection, merchant ROI or successful new bank capture.


The previously authorized ngrok endpoint was restored to the webhook-only
127.0.0.1:8002 upstream. A signed harmless connection check returned 200 ignored;
public docs, configuration, checkout and readiness paths returned 404. A fresh
oversized public request encountered a connection reset before a response could
be observed, so no new public HTTP 413 result is claimed. The body-limit regression
suite passed as part of the 604-test local run.


## 10 November: alternate-method capture and reviewed settlement completed

This supersedes the earlier unpaid-link checkpoint above. The owner completed
Cards and the mock Success step on the existing Test link. Fresh provider reads
confirmed `plink_Ty6mI38swZvUFp` is paid, amount INR 499.00, amount_paid 49,900 paise,
currency INR. Payment `pay_TyJMPHDeiTY6Ha` is captured for 49,900 paise by `card`,
different from the excluded original failed method `netbanking`. No new checkout
resource was created to complete this acceptance check.

The case was still held in `needs_reconciliation`. The existing reviewed-success
service re-fetched provider evidence under its exclusive reconciliation claim and
verified the original order, exact execution amount/currency and alternate captured
method. It settled execution 3 on original case `pay_Ty6QWwHiy3qICK` as recovered,
recorded one attributed `alt_method` success outcome, released the claim and left
zero pending reviews. The earlier retry outcome remains failed. This is reviewed
settlement, not a claim that the held case auto-settled on webhook delivery.

The signed capture event `TyJMfHZoOBpWxT` reached the verified inbox. It was retryable
while the case was blocked. After settlement it was processed (attempt 7).
The saved record does not distinguish worker replay from provider redelivery.
By the time an explicit targeted replay check ran, it selected zero events. Repeating that check also selected zero: executions stayed two and outcomes
two (one failed retry, one successful alternate), with no added recovery resource
or duplicated outcome. No held/active claim was forcibly reset.

Order-level Test Mode reporting now shows four tracked original orders, three
recovered groups and INR 1,497.00 recovered amount, with no investigation group.
These are simulated provider transactions, not merchant revenue. The browser
clicks were performed by the owner; backend/provider verification and reviewed
settlement were performed by the assistant on the owner's behalf. Browser
automation remained unavailable. A successful fresh retry/mock-bank popup flow
and real merchant validation remain outstanding.


The relevant reconciliation, inbox, reporting, execution and webhook regression
suites passed **112 tests** after this acceptance check. The application code
remains the same version covered by the full 604-test run; only documentation
was updated for the new provider-origin Test evidence. A sanitized private JSON
snapshot is retained under ignored D-drive `var/acceptance-capture-20261110.json`;
no contacts, credentials or database files are committed.
