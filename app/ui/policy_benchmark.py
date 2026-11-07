"""Display recorded, matched synthetic evidence without rerunning evaluation."""

import json

import pandas as pd
import streamlit as st

from app.services.benchmark_reporting import load_benchmark_report


LABELS = {'blanket_retry':'Blanket retry (guarded)', 'cause_rules':'Cause-based rules',
          'ml_value_only':'ML value ranking (ablation)', 'ml_guarded':'ML with review guardrails'}


def render_policy_benchmark(report_path=None):
    st.subheader('Matched synthetic policy benchmark')
    st.warning('Synthetic evidence only. These numbers do not establish merchant revenue uplift.')
    try:
        report = load_benchmark_report(report_path)
    except FileNotFoundError:
        st.info('Generate the report with python -m ML.benchmark_policies before viewing benchmark metrics.')
        return
    except (ValueError, KeyError, TypeError):
        st.error('Benchmark evidence is stale or invalid. Regenerate it with python -m ML.benchmark_policies.')
        return
    primary = next(split for split in report['splits'] if split['seed'] == report['primary_seed'])
    st.caption(f"Seed {primary['seed']}: {primary['train_contexts']} training / {primary['test_contexts']} held-out contexts; zero context overlap. All policies share the same labels, costs and one-intervention budget.")
    rows = []
    for policy, metrics in primary['policies'].items():
        rows.append({'Policy':LABELS[policy], 'Interventions':metrics['interventions'],
            'Deferred reviews':metrics['reviewed_later_not_simulated'], 'Recovered automatically':metrics['recovered'],
            'Recovery rate':f"{metrics['recovery_rate']:.1%}", 'Cost (Rs)':metrics['action_cost_rupees'],
            'Immediate net (Rs)':metrics['net_recovered_rupees']})
    frame = pd.DataFrame(rows)
    st.dataframe(frame, hide_index=True, alt='Matched synthetic recovery policies with costs, automatic recoveries and deferred reviews')
    st.bar_chart(frame.set_index('Policy')['Immediate net (Rs)'], alt='Immediate synthetic net recovery by policy on the primary held-out split')
    comparison = report['primary_comparisons']['ml_value_only']
    low, high = comparison['net_delta_95_percentile_interval']
    st.write(f"ML value ranking minus cause rules: Rs.{comparison['net_delta_rupees']:,.2f}; paired 95% bootstrap interval [Rs.{low:,.2f}, Rs.{high:,.2f}].")
    if low <= 0 <= high:
        st.info('This sample does not establish a clear ML advantage over cause-based rules.')
    st.caption('Deferred human reviews remain unresolved here. Guarded-policy numbers measure immediate automatic recovery, not recovery after review. Reviewer labor and later decisions are not simulated.')
    with st.expander('Assumptions and repeated-split results'):
        for item in report['assumptions'] + report['limitations']:
            st.write(item)
        repeated = [{'Seed':split['seed'], 'Policy':LABELS[policy],
            'Net (Rs)':metrics['net_recovered_rupees'], 'Recovery rate':metrics['recovery_rate']}
            for split in report['splits'] for policy, metrics in split['policies'].items()]
        st.dataframe(repeated, hide_index=True, alt='Per-split synthetic policy results; overlapping test groups must not be pooled')
        st.json(report['config'])
    st.download_button('Download benchmark JSON',json.dumps(report,indent=2),
                       file_name='policy_benchmark.json',mime='application/json',key='benchmark_download')
