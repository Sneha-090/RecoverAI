import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from ML.benchmark_policies import (ACTIONS, POLICIES, BenchmarkConfig, choose,
    evaluate_policy, paired_interval, run_benchmark, validate_contexts, write_report)
from ML.train_model import split_contexts


@pytest.fixture
def contexts():
    rows = []
    causes = ['network_error', 'card_declined', 'insufficient_funds', 'bank_declined']
    for i in range(60):
        for index, action in enumerate(ACTIONS):
            rows.append({'customer_id': f'context_{i:03d}', 'amount': 499+i, 'cause': causes[i%4],
                'attempts': i%4, 'days_since_failure': i%15, 'past_rate': (i%5)/4,
                'action_type': action, 'recovered': (i+index)%2})
    return pd.DataFrame(rows)


@pytest.mark.parametrize('damage', ['duplicate', 'missing_action', 'different_features', 'invalid_outcome'])
def test_malformed_potential_outcome_table_is_rejected(contexts, damage):
    if damage == 'duplicate':
        contexts = pd.concat([contexts, contexts.iloc[[0]]])
    elif damage == 'missing_action':
        contexts = contexts.iloc[1:]
    elif damage == 'different_features':
        contexts.loc[0, 'amount'] = 100
    else:
        contexts.loc[0, 'recovered'] = 7
    with pytest.raises(ValueError):
        validate_contexts(contexts)


def test_evaluation_reads_fixed_labels_not_model_probabilities(contexts):
    table = contexts.iloc[:3].copy()
    table['amount'] = 100
    table['cause'] = 'card_declined'
    table['recovered'] = [0, 1, 0]
    # Model says retry is almost certain; its stored synthetic label says failure.
    metrics, rows = evaluate_policy(table, np.array([.99, .01, .01]), 'ml_value_only', BenchmarkConfig(), 42)
    assert metrics['recovered'] == 0
    assert metrics['net_recovered_rupees'] == -5
    rules, _ = evaluate_policy(table, np.array([.99, .01, .01]), 'cause_rules', BenchmarkConfig(), 42)
    assert rules['gross_recovered_rupees'] == 100
    assert rules['action_cost_rupees'] == 15
    assert rows[0]['chosen_action'] == 'retry'


def test_labels_cannot_change_selected_actions(contexts):
    scores = np.tile([.8, .3, .2], len(contexts)//3)
    for policy in POLICIES:
        _, original = evaluate_policy(contexts, scores, policy, BenchmarkConfig(), 42)
        changed = contexts.copy(); changed['recovered'] = 1-changed['recovered']
        _, altered = evaluate_policy(changed, scores, policy, BenchmarkConfig(), 42)
        assert [(row['chosen_action'], row['decision_type']) for row in original] == [
            (row['chosen_action'], row['decision_type']) for row in altered]


@pytest.mark.parametrize('policy', POLICIES)
def test_shared_window_and_high_value_guards(policy):
    context = {'amount': 499, 'cause': 'network_error', 'attempts': 0, 'days_since_failure': 14}
    assert choose(policy, context, dict.fromkeys(ACTIONS, .9), BenchmarkConfig()) == (None, 'skip')
    context.update(amount=60000, days_since_failure=0)
    assert choose(policy, context, dict.fromkeys(ACTIONS, .9), BenchmarkConfig()) == (None, 'human_review')


def test_retry_budget_and_review_deferral_are_not_simulated_as_success(contexts):
    context = {'amount': 499, 'cause': 'network_error', 'attempts': 3, 'days_since_failure': 0}
    assert choose('blanket_retry', context, dict.fromkeys(ACTIONS,.9), BenchmarkConfig()) == (None,'skip')
    assert choose('cause_rules', context, dict.fromkeys(ACTIONS,.9), BenchmarkConfig())[0] != 'retry'
    table = contexts.iloc[:3]
    metrics, rows = evaluate_policy(table, np.full(3,.5), 'ml_guarded', BenchmarkConfig(), 42)
    assert metrics['reviewed_later_not_simulated'] == 1
    assert metrics['interventions'] == metrics['recovered'] == 0
    assert rows[0]['net_paise'] == 0


def test_reproducibility_context_holdout_and_common_budget(contexts, tmp_path):
    dataset = tmp_path/'data.csv'; contexts.to_csv(dataset,index=False)
    report, decisions = run_benchmark(dataset, (42,11), 100)
    again, repeat = run_benchmark(dataset, (42,11), 100)
    assert report == again
    pd.testing.assert_frame_equal(decisions, repeat)
    for split in report['splits']:
        train, test = split_contexts(contexts, split['seed'])
        selected = decisions[decisions.split_seed == split['seed']]
        assert set(selected.context_id) == set(test.customer_id)
        assert not set(selected.context_id) & set(train.customer_id)
        for policy in POLICIES:
            rows = selected[selected.policy == policy]
            assert len(rows) == test.customer_id.nunique()
            assert rows.groupby('context_id').executed.sum().max() <= 1
        assert split['overlapping_contexts'] == 0
    write_report(report, decisions, tmp_path/'output')
    stored = json.loads((tmp_path/'output/policy_benchmark.json').read_text())
    assert stored['decisions_sha256']
    assert 'not merchant uplift' in stored['scope']


def test_paired_self_comparison_has_zero_difference():
    rows = [{'context_id':'a','net_paise':100,'success':True},
            {'context_id':'b','net_paise':-500,'success':False}]
    result = paired_interval(rows, rows, 100)
    assert result['net_delta_rupees'] == 0
    assert result['net_delta_95_percentile_interval'] == [0,0]
    with pytest.raises(ValueError):
        paired_interval(rows, list(reversed(rows)), 100)


def test_sequential_budget_is_rejected(contexts, tmp_path):
    dataset = tmp_path/'data.csv'; contexts.to_csv(dataset,index=False)
    with pytest.raises(ValueError, match='single-intervention'):
        run_benchmark(dataset, (42,), 100, BenchmarkConfig(intervention_budget=3))


def test_cli_runs_without_credentials_and_does_not_create_merchant_database(contexts, tmp_path):
    dataset = tmp_path/'data.csv'; contexts.to_csv(dataset,index=False)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('RAZORPAY_') or key in {'DATABASE_URL','OPERATOR_PASSWORD_HASH'}:
            env.pop(key)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable,'-m','ML.benchmark_policies','--dataset',str(dataset),
        '--output-dir',str(tmp_path/'output'),'--seeds','42','--bootstrap-repetitions','100'],
        cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'output/POLICY_BENCHMARK.md').exists()
    assert not (tmp_path/'recoverai.db').exists()
