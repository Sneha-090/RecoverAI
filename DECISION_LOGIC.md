# RecoverAI — Decision Logic

This document explains exactly how RecoverAI decides what to do with a failed payment — the full path from diagnosis to a final `auto` / `human_review` / `skip` decision.

It is written directly from the current implementation (`app/services/diagnosis.py`, `app/services/ml_service.py`, `app/services/eligibility.py`, `app/services/decision.py`), not from the original design spec, so it reflects what the code actually does today.

---

## 1. Overview

```text
Payment (failed)
      |
      v
1. Diagnosis            -> cause (string)
      |
      v
2. ML Prediction        -> probability per candidate action
      |
      v
3. Eligibility Check    -> is "retry" allowed right now?
      |
      v
4. Already-Tried Filter -> exclude actions already executed for this payment
      |
      v
5. Cost-Adjusted Scoring -> score = P(success) x amount - action_cost
      |
      v
6. Decision Policy      -> auto / human_review / skip
      |
      v
7. Persistence          -> every prediction + score + reason saved for audit
```

The entry point is `app/services/decision.py::decide(db, payment)`. Everything below happens inside a single call to that function.

---

## 2. Step 1 — Diagnosis (`diagnosis.py`)

Diagnosis is **rule-based**, not ML-based — a deterministic lookup from Razorpay's own error fields to a `cause` string. No learned weights are involved here.

Lookup order:

1. **`razorpay_error_reason`** (if present and recognized) — the most specific signal Razorpay gives:

   | error_reason | cause |
   |---|---|
   | `payment_failed` | `bank_declined` |
   | `insufficient_funds` | `insufficient_funds` |
   | `card_declined` | `card_declined` |
   | `expired_card` | `expired_card` |
   | `invalid_card` | `invalid_card` |
   | `authentication_failed` | `authentication_failed` |
   | `processing_error` | `network_error` |
   | `issuer_unavailable` | `network_error` |
   | `payment_cancelled` | `customer_cancelled` |

2. **`razorpay_error_code`** (fallback, if no matching `error_reason`):

   | error_code | cause |
   |---|---|
   | `GATEWAY_ERROR` | `bank_declined` |
   | `BAD_REQUEST_ERROR` | `bank_declined` |
   | `SERVER_ERROR` | `network_error` |

3. **Fallback** — if neither matches, cause is `unclassified_error`. Every payment always gets a cause; this function never returns null.

---

## 3. Step 2 — ML Recovery Prediction (`ml_service.py`)

For every candidate action (`retry`, `payment_link`, `alt_method`), RecoverAI predicts the probability that action will recover the payment.

**Features fed to the model** (a trained Logistic Regression pipeline, `ML/recovery_model.joblib`):

| Feature | Source |
|---|---|
| `amount` | the payment's amount |
| `cause` | output of Step 1 |
| `attempts` | count of all prior `Action` rows for this payment |
| `days_since_failure` | days since the payment was created |
| `past_rate` | this customer's historical recovery rate (`previous_recoveries / previous_failures`), or `0.5` (neutral) if no history exists |
| `action_type` | the candidate action being scored |
| `cause_action` | derived: `f"{cause}__{action_type}"` — captures cause × action interaction |

This produces a dict, e.g.:

```json
{ "retry": 0.65, "payment_link": 0.36, "alt_method": 0.20 }
```

**Important engineering note:** the `cause_action` feature must be constructed identically at training time and inference time. A mismatch here previously caused a full pipeline outage (documented in the README's "What Broke" section) — this file and the model are now kept in sync deliberately.

---

## 4. Step 3 — Retry Eligibility (`eligibility.py`)

Before `retry` can even be scored, it must pass **four deterministic checks**, run in this order — the first failing check wins and produces the reason string used in the audit trail:

| # | Check | Rule | Config |
|---|---|---|---|
| 1 | Razorpay state | Blocked if payment is already `captured`, `authorized`, or `halted` | `NON_RETRYABLE_STATES` |
| 2 | Recovery window | Blocked if more than **14 days** have passed since the payment was created | `max_recovery_window_days = 14` |
| 3 | Max attempts | Blocked if `retry` has already been used **3** times for this payment | `max_retry_attempts = 3` |
| 4 | Cooling-off | Blocked if the last `retry` was less than **4 hours** ago | `retry_cooling_off_hours = 4` |

If all four pass: `(True, "retry eligible")`.

`payment_link` and `alt_method` currently have **no additional eligibility restrictions** beyond the already-tried filter below — this is explicit in the code (`decision.py`'s persistence step logs the reason `"eligible - no additional restrictions currently checked for this action"` for these two).

---

## 5. Step 4 — Already-Tried Filter (`decision.py::get_tried_actions`)

An action is excluded from this round's candidates if it already has an `Action` row for this payment with `decision_type = "auto"`.

This is what allows the "re-score after failure" behavior: if `retry` was auto-executed and failed, the next `decide()` call for the same payment will not offer `retry` again — it moves to the next-best remaining action.

Human-approved actions are re-logged with `decision_type = "auto"` after approval, so they are correctly picked up by this same filter — a human-approved `retry` will not be offered a second time either.

---

## 6. Step 5 — Cost-Adjusted Scoring (`decision.py::score_action`)

For every remaining candidate:

```text
score(action) = P(action succeeds) x payment.amount - action_cost(action)
```

| Action | Cost |
|---|---:|
| `retry` | Rs. 5.00 |
| `payment_link` | Rs. 15.00 |
| `alt_method` | Rs. 10.00 |

This is an **expected-value** score, not a raw probability — a cheaper action with a slightly lower success probability can outscore a more expensive one. This is why RecoverAI sometimes chooses `payment_link` or `alt_method` over `retry` even when `retry` isn't blocked, and why the model doesn't just "always pick retry."

The **highest-scoring eligible action** wins and moves to the decision policy step.

---

## 7. Step 6 — Decision Policy (`decision.py::decide_from_predictions`)

Given the winning action, its score, and its probability, the final decision type is chosen in this order:

1. **No candidates left** (retry ineligible and nothing else to try, or everything already tried)
   → `decision_type = "skip"`, `chosen_action = None`

2. **Best score is at or below the score floor** (`score_floor = 0.0`)
   → `decision_type = "skip"` — recovering isn't worth the action's cost

3. **Uncertain confidence band** (`0.40 <= probability <= 0.60`) **or** **high-value payment** (`amount > Rs. 50,000`)
   → `decision_type = "human_review"` — a person must approve before anything executes

4. **Otherwise**
   → `decision_type = "auto"` — the action executes immediately without human involvement

This is the safety design: ML never gets an unconditional green light. Automation only happens when the model is confident (probability outside the 0.40–0.60 uncertainty band) **and** the payment isn't high-value enough to warrant a second pair of eyes.

---

## 8. Step 7 — Persistence (`decision.py::_persist_decision_explanation`)

Every call to `decide()` writes, for **every** candidate action (not just the winner):

- An `MLPrediction` row (probability, timestamp)
- A `RecoveryScore` row (score, cost used, eligibility, and the exact reason string)

Nothing is overwritten — each `decide()` call (initial decision, and every re-score after a failed attempt) produces a fresh, timestamped set of rows. This is what powers the dashboard's "Decision Explanation" tab and gives a complete, append-only audit trail of every option the system considered, not just the one it picked.

---

## 9. Human Review — What Happens After Escalation

If `decision_type = "human_review"`:

- The case appears in the dashboard's Human Review queue with the ML recommendation and the reason it was escalated.
- A business user can approve the recommended action **or pick a different one** — the human is never forced to follow the ML suggestion.
- Approved actions are executed for real (via `execution.py`) and logged, then re-classified as `decision_type = "auto"` in the Action table so the already-tried filter (Step 4) correctly excludes them from future rounds.
- **Timeout safety** (`escalation.py::expire_overdue_reviews`): if no human acts within **24 hours** (`human_review_timeout_hours`), the review is marked `expired` and logged. The system **never auto-executes** a risky action just because the deadline passed — this is enforced in code, not just policy.

---

## 10. Worked Example

A payment fails, is diagnosed as `network_error`, and none of the three actions have been tried yet:

| Action | Probability | Score (amount = Rs. 1,000) |
|---|---:|---:|
| retry | 0.65 | 0.65 × 1000 − 5 = **645.0** |
| payment_link | 0.36 | 0.36 × 1000 − 15 = 345.0 |
| alt_method | 0.20 | 0.20 × 1000 − 10 = 190.0 |

`retry` wins (highest score). Its probability (0.65) is outside the 0.40–0.60 uncertain band, and Rs. 1,000 is well under the Rs. 50,000 human-review threshold → **`decision_type = "auto"`**, `retry` executes immediately.

If that retry later fails and `decide()` runs again for the same payment, `retry` is now in the already-tried set and is excluded — the system re-scores `payment_link` vs `alt_method` and picks the next best option. If all three are eventually tried and fail, the next call returns `decision_type = "skip"` with reason `"all candidate actions already tried"`.

---

## 11. Where This Code Lives

| Concern | File |
|---|---|
| Cause diagnosis | `app/services/diagnosis.py` |
| ML probability prediction | `app/services/ml_service.py` |
| Retry eligibility rules | `app/services/eligibility.py` |
| Scoring + decision policy + persistence | `app/services/decision.py` |
| Human-review timeout safety | `app/services/escalation.py` |
| Tunable thresholds (costs, bands, limits) | `app/config.py` |

All of the behavior described above is exercised by the automated test suite (`tests/test_decision.py`, `tests/test_eligibility.py`, `tests/test_escalation.py`, `tests/test_diagnosis.py`, `tests/test_decision_persistence.py`).
