# First business pilot: online course fee recovery

Recommended scope: **one India-based online course creator or adult skill-training
business**, collecting one-time INR course/workshop fees through its own Razorpay
account. This is a proposed first customer segment, not evidence of merchant demand.
[Razorpay's education offering](https://razorpay.com/solutions/education/) supports
course fees and payment links, matching the existing checkout/link integration.

Example: an adult learner attempts to pay a course fee, the payment fails, and
RecoverAI helps the merchant choose and verify a suitable follow-up. A captured
payment resolves the fee obligation; an unresolved/ambiguous payment goes to the
operator instead of another automatic full-amount request.

## Initial operating agreement

- One merchant, one currency, one-time fees, and a named operator.
- Begin with merchant-approved shadow recommendations, then supervised recovery
  only after the safety/acceptance checks below pass. Keep notifications off until
  consent, contact policy and provider configuration are explicitly agreed.
- Use provider payment/order references and a merchant-owned fee/invoice reference.
  Do not infer a shared debt from matching email, phone or customer identity.
- Keep retry budgets, cooling-off, amount thresholds and action costs explicit.
  Current synthetic model probabilities and assumed costs are not merchant-tuned.
- Confirm course/seat validity and existing payment/refund/dispute state before a
  follow-up. Cancellation, opt-out and operator stop must prevent further contact.

## Required before live collection

1. **Underlying fee/order ownership:** multiple failed payment attempts for the
   same original order must not create independent recovery requests. An original
   order that later succeeds must stop recovery, and natural checkout success must
   not be counted as ML-attributed recovered revenue. This is an open engineering
   gap; current claims primarily protect one original payment ID.
2. Merchant-approved invoice mapping, consent/opt-out, cancellation/refund/dispute
   exclusions, and a reviewed route for partial or duplicate payments.
3. Fresh hosted Test Mode acceptance of retry, alternative method and manual review;
   complete event delivery, exact attribution and unpaid-link cleanup checks.
4. Reviewed HTTPS deployment, authenticated operator access with rate limiting,
   owned worker restarts, job-progress monitoring, alerts and tested backup restore.
   The local supervisor is an operations improvement, not a hosted deployment.
5. Written merchant authorization, restricted data access/retention, approved live
   credentials and explicit approval to begin real collection. Nothing here enables
   real-money operation or authorizes sending messages to a business.

## What to measure

Use the unique fee/order as the unit, rather than counting payment attempts as
separate customers. Record eligibility, original failure, assigned intervention,
execution and payment times, verified amount, method, operator effort, opt-outs,
and partial/duplicate/disputed outcomes. Minimize personal data in exports.

Report recovered fees and net value after measured provider/contact/operator costs.
Separate original-checkout success from recovery-resource success and Test Mode
from live results. Compare against the merchant's normal workflow using a
pre-agreed eligible holdout/randomized assignment where practical. Unchosen
recovery actions have unknown outcomes; do not label them failures to manufacture
training rows. Report sample sizes, deferrals and uncertainty before claiming uplift.

First discovery with a willing owner should establish how often failed fees occur,
how they follow up today, where invoice references live, and whether enough eligible
cases exist to learn anything useful. No business has been contacted or selected yet.
See [merchant data guide](data/MERCHANT_DATA_GUIDE.md).
