# RecoverAI: explanation and interview guide

## A short explanation

RecoverAI helps an operator handle failed payments and verify recovery outcomes.
A signed Razorpay event starts the workflow. Rules diagnose the failure and check
eligibility; a logistic model estimates action probabilities for supported
contexts, and a policy ranks actions by modeled net value. Unsupported or uncertain
contexts go to human review. The system records the exact issued order/link and
accepts success only after matching provider evidence.

The application is verified in Razorpay Test Mode. It has no production merchant
results, and the model is trained on synthetic data. Its strongest demonstrated
work is the recovery workflow, duplicate prevention and careful handling of
uncertain external calls.

Hinglish explanation: "Payment fail hone par system suitable follow-up suggest
karta hai, zaroorat par operator approval leta hai, aur sirf verified payment
capture ke baad original case ko recovered mark karta hai. Sirf checkout link
banana recovery nahi hai."

## Follow one request through the code

1. `app/webhook_gateway.py` exposes the signed-event route; operator APIs stay
   private. Raw bodies are bounded and exact bytes drive signature verification.
2. The minimal verified inbox and durable event claim reject duplicates and retain
   early/unresolved events for bounded replay.
3. Provider ingestion fetches current payment data; diagnosis and original-order
   checks prevent collection on unsupported or already-paid cases.
4. The shared policy uses eligibility, probabilities, assumed costs and review
   rules. A recommendation and an executed action are separate records.
5. A durable intent is saved before a provider request. Its eventual resource is
   bound to one RecoveryExecution, amount and currency.
6. A verified outcome is attributed to that execution. Late captures, original
   checkout success and potential duplicate collection have distinct handling.
7. Streamlit shows the case, explanation, approvals, audit and reviewed controls.

See [architecture](ARCHITECTURE.md) for the state diagram and code map.

## Demo without repeating payments

Use [the offline walkthrough](reports/OFFLINE_DEMO.md) and open
`D:\RecoverAI\reports\offline_demo.html` for recorded step-by-step replay.
Its six scenarios use real application services with a fake provider, a unique
SQLite database and blocked external networking. The replay is not a new provider
payment. The runner does not replace the configured database or credentials.

For actual Test Mode evidence, describe the recorded alternate-method flow:
original netbanking failure, explicit retry that failed, verified return to
manual review, separately approved alternate link, full card capture and reviewed
settlement. The signed capture event was processed; rechecking did not add an
execution or outcome. Three local Test recovery groups total INR 1,497. These are
simulated provider transactions, not merchant revenue.

The additional fresh retry capture was not completed. Connection faults discovered
there led to tested bounded GET handling and narrow reviewed resumption. Its unused
case was operator-stopped. Do not present that path as a successful hosted capture.

## Questions to be ready for

**Why is this more than a payment link generator?**
It handles eligibility, review, durable ownership, intent/resource attribution,
verified outcomes, reconciliation and late/duplicate events around the link.

**How do you prevent duplicates?**
Use durable event/case claims, a permanent owner per known original order, a
pre-request intent and exact execution/outcome bindings. Explain that these do
not guarantee exactly-once external charges: separate original orders for one
invoice still need merchant mapping, and previously shared checkouts can race.

**What happens when a provider request times out?**
GET reads can retry once; POST mutations do not. The initial read before ingestion
can leave a verified event replayable. A possibly accepted creation or other
ambiguous side effect stays blocked for review. An old processing timestamp is
not permission to repeat a financial request.

**Why not use a larger AI model?**
The current structured feature problem uses logistic regression. Rules enforce
business constraints. Model complexity is not evidence of business benefit.
Unknown causes/out-of-range contexts require manual assessment.

**Does ML beat rules?**
The matched synthetic benchmark does not establish a clear advantage. On its
primary split, ML value ranking minus cause rules is INR -735.83, with paired
interval [-12,971.92, 13,456.14]. The classifier report measures probability
quality; it is not a merchant recovery-rate result. Deferred reviews remain
unresolved in the policy comparison.

**How did you test it?**
The current combined suite has 645 tests across services, API security, money
validation, concurrent claims, attribution, stops, reviewed controls and headless
Streamlit UI. There are six isolated offline scenarios, actual provider-origin
Test captures, versioned migrations and an isolated backup restore drill. Local
passes and head-specific GitHub CI results are recorded separately.

**What is still missing for a business deployment?**
An approved merchant pilot and real outcomes, invoice mapping across separate
provider orders, agreed consent/refund/dispute procedures, reviewed HTTPS hosting,
rate limits, job-progress monitoring, alerts and hosted recovery procedures.
SQLite/local process supervision is not a demonstrated large-scale deployment.

## Resume bullets you can defend

- Built a FastAPI, SQLAlchemy and Streamlit payment-recovery application integrated
  with Razorpay Test Mode, signed webhooks, explicit operator review and verified
  execution-level settlement.
- Implemented original-order recovery ownership, durable request intents, duplicate
  guards, persistent operator stops and reviewed reconciliation; validated with a
  645-test regression suite and CI.
- Evaluated logistic-regression recovery policies on grouped held-out synthetic
  contexts against matched baselines, reporting calibration, uncertainty and the
  absence of demonstrated real-world revenue uplift.

Adapt the number of bullets to the role. State "Test Mode" and "synthetic" clearly;
do not claim production users, merchant ROI, guaranteed recovery or measured
latency that was not actually benchmarked.
