# Synthetic policy benchmark

**Synthetic evidence only. No merchant revenue or production uplift claim.**

Primary split: seed 42; 1600 training and 400 held-out contexts; zero context overlap.

| Policy | Interventions | Reviews deferred | Recovered | Recovery rate | Gross Rs | Cost Rs | Net Rs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| blanket_retry | 284 | 0 | 94 | 23.5% | 84771.94 | 1420.00 | 83351.94 |
| cause_rules | 373 | 0 | 133 | 33.2% | 134744.90 | 3555.00 | 131189.90 |
| ml_value_only | 370 | 0 | 129 | 32.2% | 134454.07 | 4000.00 | 130454.07 |
| ml_guarded | 301 | 69 | 91 | 22.8% | 101494.70 | 3365.00 | 98129.70 |

## Paired net difference against cause rules

| Policy | Net difference Rs | 95% paired bootstrap interval Rs |
| --- | ---: | --- |
| blanket_retry | -47837.96 | [-80771.60, -18731.05] |
| ml_value_only | -735.83 | [-12971.92, 13456.14] |
| ml_guarded | -33060.20 | [-50707.89, -14531.18] |

Intervals crossing zero do not provide clear evidence of an advantage on this synthetic sample.

Human-review cases are unresolved here: guarded results measure immediate automatic recovery, not recovery after review.

## Repeated split means (overlapping test sets; do not pool customers)

| Policy | Mean net Rs | Mean recovery rate | Mean interventions | Mean deferred reviews |
| --- | ---: | ---: | ---: | ---: |
| blanket_retry | 84245.58 | 22.7% | 283.4 | 0.0 |
| cause_rules | 118627.95 | 30.8% | 375.0 | 0.0 |
| ml_value_only | 118064.14 | 30.8% | 372.4 | 0.0 |
| ml_guarded | 84802.07 | 21.6% | 299.4 | 73.0 |

## Assumptions

- Each synthetic context supplies one fixed potential-outcome label for every action; selectors cannot inspect labels.
- All policies share the same test contexts, costs, one-intervention budget and recovery-window/high-value guards.
- The dataset lacks retry-specific history/cooling-off timestamps: prior attempts are assumed failed retries and cooling-off satisfied.
- Cause rules are fixed before evaluation; no rule or threshold is tuned to these results.
- ml_guarded reuses application confidence deferral; ml_value_only is an ablation with that deferral disabled.
- Deferred human reviews contribute zero immediate recovery and no action cost; reviewer labor or later decisions are not simulated.

## Limits

- Synthetic potential outcomes cannot establish real intervention effectiveness or merchant revenue uplift.
- No sequential retry uplift is estimated: outcomes were generated at the original context, not after new attempts.
- Repeated split test sets overlap across runs; their counts must not be pooled as independent customers.
- Bootstrap intervals are conditional on the primary synthetic sample and fitted model, not a production guarantee.
- The model is refitted on each training partition only; the application model file and merchant database are untouched.

Full per-split metrics and provenance: [JSON](policy_benchmark.json). Auditable case decisions: [CSV](policy_decisions.csv).
