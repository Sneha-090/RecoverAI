# Offline recovery walkthrough

OFFLINE SIMULATION: real app services, fake provider, isolated SQLite, outbound network blocked

No merchant database, .env file or external payment is changed. Each run creates a new SQLite fixture.

## 1. Signed failure, duplicate protection and verified recovery

- A signed failure reaches the real webhook route and ML/policy pipeline.
- The same event is delivered twice; the second delivery is acknowledged without another resource.
- An invalid signature is rejected with HTTP 400.
- An unpaid resource stays pending; no follow-up resource is created.
- A verified captured event settles the original case once.

Result: **recovered**; simulated provider creations: 1; stored outcomes: 1.

## 2. High-value recovery requires human approval

- A high-value case enters review; no provider resource exists yet.
- The demo operator explicitly approves an untried recovery action.
- Only then is one simulated provider resource created.
- Captured payment evidence closes the original case.

Result: **recovered**; simulated provider creations: 1; stored outcomes: 1.

## 3. Lost creation response is reconciled without repeating payment

- The provider accepts creation, then the simulated response is lost.
- The case is blocked for reconciliation; automatic creation is not retried.
- The operator checks the existing resource; intent notes, amount and currency must match.
- Fresh verification settles the case with one resource; the uncertain webhook is not forcibly replayed.

Result: **recovered**; simulated provider creations: 1; stored outcomes: 1.

## 4. Late success is matched to the older retry

- The operator approves an initial retry order.
- That attempt reports failure, and a different recovery action is selected/approved.
- A delayed capture arrives for the old order.
- The old execution result is upgraded to success; no extra recovery action starts.

Result: **recovered**; simulated provider creations: 2; stored outcomes: 1.

## 5. Review deadline closes a case without a risky action

- A high-value failure waits for human review.
- The fixture advances the review deadline; no approval is supplied.
- The real maintenance service expires the review, closes the failed case and clears its review claim.
- Zero provider resources are created.

Result: **closed_unrecovered**; simulated provider creations: 0; stored outcomes: 0.

## 6. Early capture survives until execution persistence

- A signed capture arrives before the creation response and execution audit are saved.
- The verified event is durably stored as waiting for execution.
- The original creation response finishes and binds the execution.
- The real replay worker matches the event and settles once.

Result: **recovered**; simulated provider creations: 1; stored outcomes: 1.
