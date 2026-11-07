# Synthetic policy benchmark

**Synthetic evidence only. No merchant revenue or production uplift claim.**

Primary split: seed 42; 1600 training and 400 held-out contexts; zero context overlap.

| Policy | Interventions | Reviews deferred | Recovered | Recovery rate | Gross Rs | Cost Rs | Net Rs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| blanket_retry | 284 | 0 | 94 | 23.5% | 84771.94 | 1420.00 | 83351.94 |
| cause_rules | 373 | 0 | 133 | 33.2% | 134744.90 | 3555.00 | 131189.90 |
| ml_value_only | 370 | 0 | 129 | 32.2% | 134454.07 | 4000.00 | 130454.07 |
| ml_guarded | 341 | 29 | 126 | 31.5% | 132713.23 | 3610.00 | 129103.23 |

## Paired net difference against cause rules

| Policy | Net difference Rs | 95% paired bootstrap interval Rs |
| --- | ---: | --- |
| blanket_retry | -47837.96 | [-80771.60, -18731.05] |
| ml_value_only | -735.83 | [-12971.92, 13456.14] |
| ml_guarded | -2086.67 | [-14517.82, 12088.70] |

Intervals crossing zero do not provide clear evidence of an advantage on this synthetic sample.

Human-review cases are unresolved here: guarded results measure immediate automatic recovery, not recovery after review.

## Repeated split means (overlapping test sets; do not pool customers)

| Policy | Mean net Rs | Mean recovery rate | Mean interventions | Mean deferred reviews |
| --- | ---: | ---: | ---: | ---: |
| blanket_retry | 84245.58 | 22.7% | 283.4 | 0.0 |
| cause_rules | 118627.95 | 30.8% | 375.0 | 0.0 |
| ml_value_only | 118064.14 | 30.8% | 372.4 | 0.0 |
| ml_guarded | 112717.97 | 28.6% | 310.0 | 62.4 |

## Assumptions

- Each synthetic context supplies one fixed potential-outcome label for every action; selectors cannot inspect labels.
- All policies share the same test contexts, costs, one-intervention budget and recovery-window/high-value guards.
- The dataset lacks retry-specific history/cooling-off timestamps: prior attempts are assumed failed retries and cooling-off satisfied.
- Synthetic contexts assume a supported original method and available alternative checkout methods; method availability and switching effectiveness are not observed.
- The 2% default near-tie margin is a predeclared business assumption, not learned confidence or tuned to test results.
- Cause rules are fixed before evaluation; no rule or threshold is tuned to these results.
- ml_guarded reuses the configured near-tie net-value review guard; ml_value_only disables that guard. The margin is not statistical confidence.
- Deferred human reviews contribute zero immediate recovery and no action cost; reviewer labor or later decisions are not simulated.

## Limits

- Synthetic potential outcomes cannot establish real intervention effectiveness or merchant revenue uplift.
- No sequential retry uplift is estimated: outcomes were generated at the original context, not after new attempts.
- Repeated split test sets overlap across runs; their counts must not be pooled as independent customers.
- Bootstrap intervals are conditional on the primary synthetic sample and fitted model, not a production guarantee.
- The model is refitted on each training partition only; the application model file and merchant database are untouched.

Full per-split metrics and provenance: [JSON](policy_benchmark.json). Auditable case decisions: [CSV](policy_decisions.csv).
