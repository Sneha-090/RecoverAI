"""Operator view of source-separated decision and execution counts."""

import pandas as pd
import streamlit as st

from app.services.action_reporting import build_action_report, SCOPES


def render_action_distribution(db):
    st.subheader('Action distribution')
    scope = st.segmented_control('Data source', list(SCOPES),
                                 default='Razorpay Test Mode', key='action_distribution_scope')
    if scope is None:
        st.info('Choose a data source to inspect recorded decisions.')
        return
    snapshot = build_action_report(db, scope)
    selected = st.selectbox('Recorded failure cause', ['All causes', *snapshot['available_causes']],
                            key='action_distribution_cause')
    if selected != 'All causes':
        snapshot = build_action_report(db, scope, selected)
    a, b, c = st.columns(3)
    a.metric('Cases in selected source/filter', snapshot['cases'])
    b.metric('First recorded decisions', snapshot['first_decisions'])
    c.metric('Cases pending human review', snapshot['pending_review_cases'])
    st.caption(f"Source: {scope}. {snapshot['cases_without_decision']} cases have no recorded decision. "
               f"{snapshot['executions']} executed actions are recorded. "
               "A review recommendation is not an execution; approving it does not create a second first decision.")
    st.info('These counts describe recorded choices. Unequal action shares can reflect the failure mix, costs and eligibility rules; '
            'they do not establish bias or action effectiveness. Test Mode uses simulated payments; simulation uses synthetic cases.')
    if not snapshot['cases']:
        st.info('No cases match this data source and cause filter.')
        return
    st.dataframe(pd.DataFrame(snapshot['distribution']), width='stretch', hide_index=True,
                 column_config={'Share of first decisions': st.column_config.NumberColumn(format='percent')},
                 alt='First recorded decisions, their shares, executed actions and human-approved executions by action')
    st.caption('First decisions use the earliest recorded Action per case. Executions count auto records, including human-approved actions. '
               'Execution totals can exceed case totals when a case progresses through different actions.')
    st.markdown('**First decisions by recorded failure cause**')
    st.dataframe(pd.DataFrame(snapshot['by_cause']), width='stretch', hide_index=True,
                 alt='Case counts and first recovery choices grouped by recorded failure cause')
    st.caption('Recorded diagnoses are historical. Unknown or missing diagnoses stay visible; existing recovered cases are not relabelled.')
