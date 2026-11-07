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
