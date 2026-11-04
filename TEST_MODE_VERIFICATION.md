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

Next priorities remain persisted execution identities and exact outcome
attribution, amount/currency validation, reviewed reconciliation of interrupted
operations, and scheduled review expiry. The protected local checkout and
dashboard login also need a separate browser smoke test with operator login.
