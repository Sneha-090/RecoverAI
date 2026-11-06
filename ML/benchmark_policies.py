"""Matched, single-intervention policy evaluation on held-out synthetic contexts.

No merchant database, credentials or provider calls. Outcomes come from the
held-out label table, never from the evaluated model's probabilities.
"""

import argparse
from dataclasses import asdict, dataclass, field
import hashlib
from io import BytesIO
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from ML.train_model import build_model, prepare_features, split_contexts
from app.services.policy import select_recovery_action
from app.services.money import amount_paise


ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ('retry', 'payment_link', 'alt_method')
POLICIES = ('blanket_retry', 'cause_rules', 'ml_value_only', 'ml_guarded')
FEATURES = ('amount', 'cause', 'attempts', 'days_since_failure', 'past_rate')
RULE_ORDER = {
    'network_error': ('retry', 'payment_link', 'alt_method'),
    'insufficient_funds': ('alt_method', 'payment_link', 'retry'),
    'card_declined': ('payment_link', 'alt_method', 'retry'),
    'bank_declined': ('alt_method', 'payment_link', 'retry'),
}


@dataclass(frozen=True)
class BenchmarkConfig:
    costs: dict = field(default_factory=lambda: {'retry': 5.0, 'payment_link': 15.0, 'alt_method': 10.0})
    max_recovery_days: int = 14
    max_prior_retries: int = 3
    human_review_amount_threshold: float = 50000.0
    score_floor: float = 0.0
    confidence_band_low: float = 0.40
    confidence_band_high: float = 0.60
    intervention_budget: int = 1


def validate_contexts(frame):
    required = {'customer_id', 'action_type', 'recovered', *FEATURES}
    if not required.issubset(frame) or frame[list(required)].isna().any().any():
        raise ValueError('Complete non-null context features, actions and outcomes are required')
    if frame.duplicated(['customer_id', 'action_type']).any():
        raise ValueError('Each context/action must appear exactly once')
    if set(frame['action_type']) != set(ACTIONS) or not set(frame['recovered']).issubset({0, 1}):
        raise ValueError('Only the three supported actions and binary outcomes are allowed')
    grouped = frame.groupby('customer_id', sort=True)
    if not grouped['action_type'].apply(lambda values: set(values) == set(ACTIONS)).all():
        raise ValueError('Every context needs all three synthetic potential outcomes')
    if (grouped[list(FEATURES)].nunique() != 1).any().any():
        raise ValueError('Features must be identical across actions for a context')
    numeric = frame[['amount', 'attempts', 'days_since_failure', 'past_rate']].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError('Numeric features must be finite')
    for name in ['attempts', 'days_since_failure']:
        if (frame[name] < 0).any() or (frame[name] % 1 != 0).any():
            raise ValueError('Attempts and age must be non-negative integers')
    if not frame['past_rate'].between(0, 1).all():
        raise ValueError('Past recovery rate must be between zero and one')
    for value in frame['amount']:
        amount_paise(value)


def choose(policy, context, predictions, config):
    """This selector receives features/predictions only, not outcome labels."""
    if policy not in POLICIES:
        raise ValueError('Unknown benchmark policy')
    if context['days_since_failure'] >= config.max_recovery_days:
        return None, 'skip'
    if context['amount'] > config.human_review_amount_threshold:
        return None, 'human_review'
    retry_ok = context['attempts'] < config.max_prior_retries
    if policy == 'blanket_retry':
        return ('retry', 'auto') if retry_ok else (None, 'skip')
    if policy == 'cause_rules':
        order = RULE_ORDER.get(context['cause'], ('payment_link', 'alt_method', 'retry'))
        return next((action, 'auto') for action in order if action != 'retry' or retry_ok)
    guarded = policy == 'ml_guarded'
    decision = select_recovery_action(
        context['amount'], predictions, retry_ok, 'prior retry budget exhausted',
        action_costs=config.costs, score_floor=config.score_floor,
        confidence_band_low=config.confidence_band_low if guarded else 2.0,
        confidence_band_high=config.confidence_band_high if guarded else 2.0,
        human_review_amount_threshold=config.human_review_amount_threshold,
    )
    return decision['chosen_action'], decision['decision_type']


def evaluate_policy(test, probabilities, policy, config, seed):
    contexts = test.groupby('customer_id', sort=True)[list(FEATURES)].first()
    labels = test.pivot(index='customer_id', columns='action_type', values='recovered')
    scores = test[['customer_id', 'action_type']].copy()
    scores['probability'] = probabilities
    scores = scores.pivot(index='customer_id', columns='action_type', values='probability')
    rows = []
    for context_id, context in contexts.iterrows():
        action, decision = choose(policy, context, scores.loc[context_id, list(ACTIONS)].to_dict(), config)
        executed = decision == 'auto' and action is not None
        success = bool(labels.loc[context_id, action]) if executed else False
        cost = amount_paise(config.costs[action]) if executed else 0
        gross = amount_paise(context['amount']) if success else 0
        rows.append({'split_seed': int(seed), 'context_id': context_id, 'policy': policy,
            'chosen_action': action, 'decision_type': decision, 'executed': bool(executed),
            'success': success, 'cost_paise': cost, 'gross_paise': gross, 'net_paise': gross-cost})
    metrics = {
        'contexts': len(rows), 'interventions': sum(row['executed'] for row in rows),
        'reviewed_later_not_simulated': sum(row['decision_type'] == 'human_review' for row in rows),
        'skipped': sum(row['decision_type'] == 'skip' for row in rows),
        'recovered': sum(row['success'] for row in rows),
        'gross_recovered_rupees': sum(row['gross_paise'] for row in rows)/100,
        'action_cost_rupees': sum(row['cost_paise'] for row in rows)/100,
        'net_recovered_rupees': sum(row['net_paise'] for row in rows)/100,
        'recovery_rate': sum(row['success'] for row in rows)/len(rows),
        'interventions_per_context': sum(row['executed'] for row in rows)/len(rows),
    }
    return metrics, rows


def paired_interval(candidate, baseline, repetitions=2000, seed=2026):
    if [row['context_id'] for row in candidate] != [row['context_id'] for row in baseline]:
        raise ValueError('Paired bootstrap requires identical context ordering')
    deltas = np.array([left['net_paise']-right['net_paise'] for left, right in zip(candidate, baseline)], dtype=float)/100
    recovered = np.array([int(left['success'])-int(right['success']) for left, right in zip(candidate, baseline)])
    rng = np.random.default_rng(seed)
    net_samples, rate_samples = [], []
    for _ in range(repetitions):
        indices = rng.integers(0, len(deltas), size=len(deltas))
        net_samples.append(float(deltas[indices].sum()))
        rate_samples.append(float(recovered[indices].mean()))
    return {'net_delta_rupees': float(deltas.sum()),
            'net_delta_95_percentile_interval': np.percentile(net_samples, [2.5, 97.5]).tolist(),
            'recovery_rate_delta': float(recovered.mean()),
            'rate_delta_95_percentile_interval': np.percentile(rate_samples, [2.5, 97.5]).tolist()}


def run_benchmark(dataset, seeds=(11, 29, 42, 73, 101), bootstrap_repetitions=2000, config=None):
    config = config or BenchmarkConfig()
    if config.intervention_budget != 1:
        raise ValueError('The label table supports only single-intervention evaluation')
    if not seeds or len(set(seeds)) != len(seeds) or not 100 <= bootstrap_repetitions <= 10000:
        raise ValueError('Use distinct split seeds and 100..10000 bootstrap repetitions')
    frame = pd.read_csv(dataset)
    validate_contexts(frame)
    all_rows, splits, primary_rows = [], [], {}
    primary_seed = 42 if 42 in seeds else seeds[0]
    for seed in seeds:
        train, test = split_contexts(frame, seed)
        model = build_model(seed).fit(prepare_features(train), train['recovered'])
        probabilities = model.predict_proba(prepare_features(test))[:, 1]
        buffer = BytesIO(); joblib.dump(model, buffer)
        metrics = {}
        for policy in POLICIES:
            metrics[policy], rows = evaluate_policy(test, probabilities, policy, config, seed)
            all_rows.extend(rows)
            if seed == primary_seed:
                primary_rows[policy] = rows
        splits.append({'seed': int(seed), 'train_contexts': train.customer_id.nunique(),
            'test_contexts': test.customer_id.nunique(),
            'overlapping_contexts': len(set(train.customer_id) & set(test.customer_id)),
            'model_sha256': hashlib.sha256(buffer.getvalue()).hexdigest(), 'policies': metrics})
    report = {'schema_version': 1, 'scope': 'synthetic single-intervention policy benchmark; not merchant uplift',
        'dataset_sha256': hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        'benchmark_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'selector_code_sha256': hashlib.sha256((ROOT/'app/services/policy.py').read_bytes()).hexdigest(),
        'sklearn_version': sklearn.__version__, 'config': asdict(config),
        'primary_seed': int(primary_seed), 'seeds': list(seeds), 'splits': splits,
        'bootstrap': {'method': 'paired context percentile bootstrap on primary split',
                      'seed': 2026, 'repetitions': bootstrap_repetitions},
        'primary_comparisons': {policy: paired_interval(primary_rows[policy], primary_rows['cause_rules'], bootstrap_repetitions)
                                for policy in POLICIES if policy != 'cause_rules'},
        'mean_across_splits': {policy: {key: float(np.mean([split['policies'][policy][key] for split in splits]))
                                      for key in ['net_recovered_rupees','recovery_rate','interventions','reviewed_later_not_simulated']}
                               for policy in POLICIES},
        'assumptions': [
            'Each synthetic context supplies one fixed potential-outcome label for every action; selectors cannot inspect labels.',
            'All policies share the same test contexts, costs, one-intervention budget and recovery-window/high-value guards.',
            'The dataset lacks retry-specific history/cooling-off timestamps: prior attempts are assumed failed retries and cooling-off satisfied.',
            'Cause rules are fixed before evaluation; no rule or threshold is tuned to these results.',
            'ml_guarded reuses application confidence deferral; ml_value_only is an ablation with that deferral disabled.',
            'Deferred human reviews contribute zero immediate recovery and no action cost; reviewer labor or later decisions are not simulated.',
        ],
        'limitations': [
            'Synthetic potential outcomes cannot establish real intervention effectiveness or merchant revenue uplift.',
            'No sequential retry uplift is estimated: outcomes were generated at the original context, not after new attempts.',
            'Repeated split test sets overlap across runs; their counts must not be pooled as independent customers.',
            'Bootstrap intervals are conditional on the primary synthetic sample and fitted model, not a production guarantee.',
            'The model is refitted on each training partition only; the application model file and merchant database are untouched.',
        ]}
    return report, pd.DataFrame(all_rows)


def write_report(report, decisions, output_dir):
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    csv = output/'policy_decisions.csv'; decisions.to_csv(csv, index=False)
    report['decisions_sha256'] = hashlib.sha256(csv.read_bytes()).hexdigest()
    (output/'policy_benchmark.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    primary = next(split for split in report['splits'] if split['seed'] == report['primary_seed'])
    lines = ['# Synthetic policy benchmark', '', '**Synthetic evidence only. No merchant revenue or production uplift claim.**', '',
        f"Primary split: seed {report['primary_seed']}; {primary['train_contexts']} training and {primary['test_contexts']} held-out contexts; zero context overlap.", '',
        '| Policy | Interventions | Reviews deferred | Recovered | Recovery rate | Gross Rs | Cost Rs | Net Rs |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for policy, metrics in primary['policies'].items():
        lines.append(f"| {policy} | {metrics['interventions']} | {metrics['reviewed_later_not_simulated']} | {metrics['recovered']} | {metrics['recovery_rate']:.1%} | {metrics['gross_recovered_rupees']:.2f} | {metrics['action_cost_rupees']:.2f} | {metrics['net_recovered_rupees']:.2f} |")
    lines += ['', '## Paired net difference against cause rules', '', '| Policy | Net difference Rs | 95% paired bootstrap interval Rs |', '| --- | ---: | --- |']
    for policy, comparison in report['primary_comparisons'].items():
        low, high = comparison['net_delta_95_percentile_interval']
        lines.append(f"| {policy} | {comparison['net_delta_rupees']:.2f} | [{low:.2f}, {high:.2f}] |")
    lines += ['', 'Intervals crossing zero do not provide clear evidence of an advantage on this synthetic sample.', '',
              'Human-review cases are unresolved here: guarded results measure immediate automatic recovery, not recovery after review.', '',
              '## Repeated split means (overlapping test sets; do not pool customers)', '',
              '| Policy | Mean net Rs | Mean recovery rate | Mean interventions | Mean deferred reviews |',
              '| --- | ---: | ---: | ---: | ---: |']
    for policy, values in report['mean_across_splits'].items():
        lines.append(f"| {policy} | {values['net_recovered_rupees']:.2f} | {values['recovery_rate']:.1%} | {values['interventions']:.1f} | {values['reviewed_later_not_simulated']:.1f} |")
    lines += ['', '## Assumptions', '', *['- '+text for text in report['assumptions']], '', '## Limits', '',
              *['- '+text for text in report['limitations']], '',
              'Full per-split metrics and provenance: [JSON](policy_benchmark.json). Auditable case decisions: [CSV](policy_decisions.csv).', '']
    (output/'POLICY_BENCHMARK.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'data/synthetic_payments.csv')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'reports')
    parser.add_argument('--seeds', type=int, nargs='+', default=[11,29,42,73,101])
    parser.add_argument('--bootstrap-repetitions', type=int, default=2000)
    args = parser.parse_args()
    report, decisions = run_benchmark(args.dataset, args.seeds, args.bootstrap_repetitions)
    write_report(report, decisions, args.output_dir)
    print(json.dumps({'primary_seed': report['primary_seed'], 'mean_across_splits': report['mean_across_splits'],
                      'primary_comparisons': report['primary_comparisons']}, indent=2))
    print(f'Report: {args.output_dir / "POLICY_BENCHMARK.md"}')


if __name__ == '__main__':
    main()
