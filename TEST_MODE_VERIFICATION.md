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
