"""
RecoverAI Dashboard - Streamlit app.

Organized into tabs to reduce scroll clutter.
"""

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import settings
from app.db.session import SessionLocal
from app.models.models import (
    Action,
    AuditLog,
    Diagnosis,
    DecisionType,
    MLPrediction,
    Outcome,
    Payment,
    RecoveryScore,
    ReviewStatus,
    RecoveryReservation,
    OriginalOrderRecovery,
)
from app.services.execution import human_review_action
from app.ui.operator_login import require_dashboard_operator
from app.ui.reconciliation import render_reconciliation
from app.ui.policy_benchmark import render_policy_benchmark
from app.ui.action_distribution import render_action_distribution
from app.ui.checkout_maintenance import render_checkout_maintenance
from app.ui.recovery_stops import render_recovery_stop
from app.services.order_reporting import build_order_summary
from app.services.case_views import find_live_cases, case_timeline


# =====================================================
# PAGE SETUP
# =====================================================

st.set_page_config(
    page_title="RecoverAI Dashboard",
    layout="wide",
)

st.title("RecoverAI — Recovery Dashboard")

operator_username = require_dashboard_operator()

db = SessionLocal()


# =====================================================
# TOP-LEVEL RECOVERY SNAPSHOT
# =====================================================

impact_snapshot = build_order_summary(db, "Razorpay Test Mode")

kpi1, kpi2, kpi3 = st.columns(3)

kpi1.metric(
    "Test Mode orders / standalone cases",
    impact_snapshot["tracked_groups"],
)

kpi2.metric(
    "Recovered Test Mode groups",
    impact_snapshot["recovered_groups"],
)

kpi3.metric(
    "Test Mode amount recovered",
    f"Rs.{impact_snapshot['recovered_amount']:,.2f}",
)

st.caption(
    f"{impact_snapshot['payment_attempts']} Test Mode payment attempts across "
    f"{impact_snapshot['known_orders']} known orders and {impact_snapshot['standalone_payments']} unlinked payments. "
    f"{impact_snapshot['paid_original_groups']} groups paid at the original checkout; "
    f"{impact_snapshot['investigation_groups']} groups need investigation. Both are excluded from recovered revenue. "
    "Multiple attempts for one order count once. Unlinked payments cannot be deduplicated across invoices. "
    "No real merchant revenue is represented; synthetic results stay separate."
)


# =====================================================
# HELPERS
# =====================================================

def get_recovery_order_info(payment_id: str):
    """Only the latest active checkout; never offer an earlier completed resource."""
    payment = db.get(Payment, payment_id)
    if not payment or payment.status != 'failed' or payment.recovery_stop_reason:
        return None
    if payment.order_id:
        scope = db.get(OriginalOrderRecovery, payment.order_id)
        if not scope or scope.state != 'active' or scope.payment_id != payment_id:
            return None
    claim = db.get(RecoveryReservation, payment_id)
    if claim is None or claim.state != 'awaiting_outcome':
        return None
    audit = db.query(AuditLog).filter(
        AuditLog.payment_id == payment_id,
        AuditLog.event_type.in_(['executed', 'human_approved_executed']),
    ).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).first()
    try:
        payload = json.loads(audit.payload_json) if audit else {}
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if payload.get('type') in {'order','payment_link'} else None


# =====================================================
# TABS
# =====================================================

(
    tab_live,
    tab_distribution,
    tab_batch,
    tab_review,
    tab_reconciliation,
    tab_guardrails,
    tab_impact,
    tab_explain,
) = st.tabs(
    [
        "Live Razorpay Cases",
        "Action Distribution",
        "Case Simulation",
        "Human Review",
        "Recovery Review",
        "Guardrails",
        "Policy Benchmark",
        "Decision Explanation",
    ]
)


with tab_distribution:
    render_action_distribution(db)


# =====================================================
# TAB 1: LIVE RAZORPAY CASES
# =====================================================

with tab_live:

    st.caption(
        "Real Razorpay test-mode payments processed through RecoverAI."
    )

    render_recovery_stop(db, operator_username)
    search_column, status_column = st.columns([2,1])
    with search_column:
        case_search = st.text_input('Search payment ID', max_chars=128, key='live_case_search')
    with status_column:
        case_status = st.selectbox('Case status',
            ['All statuses','failed','recovered','paid_original','needs_reconciliation','closed_unrecovered','authorized','captured'], key='live_case_status')
    live_payments = find_live_cases(db,case_search,case_status)
    st.caption('Showing up to 200 newest matching Test Mode cases. paid_original means paid at the original checkout, excluded from recovered revenue. needs_reconciliation requires investigation; no new collection is allowed.')

    if not live_payments:

        st.info(
            "No Test Mode cases match the selected search and status."
        )

    else:

        rows = []

        for payment in live_payments:

            diagnosis = (
                db.query(Diagnosis)
                .filter(
                    Diagnosis.payment_id
                    == payment.payment_id
                )
                .first()
            )

            actions = (
                db.query(Action)
                .filter(
                    Action.payment_id
                    == payment.payment_id
                )
                .order_by(Action.chosen_at)
                .all()
            )

            outcomes = (
                db.query(Outcome)
                .filter(
                    Outcome.payment_id
                    == payment.payment_id
                )
                .order_by(Outcome.observed_at)
                .all()
            )

            scope = db.get(OriginalOrderRecovery, payment.order_id) if payment.order_id else None
            rows.append(
                {
                    "Payment ID": payment.payment_id,
                    "Original order": payment.order_id or 'Not supplied',
                    "Recovery stop": payment.recovery_stop_reason or 'None',
                    "Recovery owner": scope.payment_id or 'Investigation required' if scope else 'Not bound',
                    "Original order state": scope.state if scope else 'Not bound',
                    "Amount (Rs)": payment.amount,
                    "Cause": (
                        diagnosis.cause
                        if diagnosis
                        else "unknown"
                    ),
                    "Executed Actions": ", ".join(
                        action.action_type for action in actions if action.decision_type == DecisionType.auto
                    ) or "none",
                    "Pending Review": ", ".join(
                        action.action_type for action in actions if action.review_status == ReviewStatus.pending
                    ) or "none",
                    "Decision Type": (
                        actions[-1].decision_type.value
                        if actions
                        else "-"
                    ),
                    "Last Outcome": (
                        outcomes[-1].observed_result
                        if outcomes
                        else "pending"
                    ),
                    "Final Status": payment.status,
                }
            )

        # -------------------------------------------------
        # MAIN PAYMENT TABLE
        # -------------------------------------------------

        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
        )

        # -------------------------------------------------
        # RECOVERY ACTIONS
        # -------------------------------------------------

        st.subheader(
            "Available Recovery Actions"
        )

        recovery_action_found = False

        for payment in live_payments:

            # Once the original case is recovered,
            # there is no reason to show another retry link.
            if payment.status != "failed":
                continue

            recovery = get_recovery_order_info(
                payment.payment_id
            )

            if recovery and recovery['type'] == 'order':
                recovery_action_found = True
                checkout_url = f"{settings.api_base_url.rstrip('/')}/checkout?order_id={recovery['order_id']}"
                st.markdown(f"**{payment.payment_id}** | Rs.{payment.amount:,.2f} | "
                            f"[Open fresh retry checkout]({checkout_url})")
                st.caption('Operator Test Mode checkout. The customer must explicitly make a new payment; no automatic debit occurs.')
            elif recovery and recovery['type'] == 'payment_link':
                from urllib.parse import urlparse
                url = recovery.get('short_url') or ''
                parsed = urlparse(url)
                if parsed.scheme == 'https' and parsed.netloc in {'rzp.io','razorpay.com'}:
                    recovery_action_found = True
                    label = 'Open alternate-method checkout' if recovery.get('excluded_method') else 'Open recovery payment link'
                    st.markdown(f"**{payment.payment_id}** | Rs.{payment.amount:,.2f} | [{label}]({url})")
                    if recovery.get('excluded_method'):
                        st.caption(f"Original method {recovery['excluded_method']} is hidden. Available checkout methods depend on the Razorpay account.")

        if not recovery_action_found:

            st.caption(
                "No active recovery checkout is awaiting payment."
            )


# =====================================================
# TAB 2: BATCH EVALUATION
# =====================================================

with tab_batch:

    st.caption(
        "Optional synthetic case walkthrough. Outcomes are simulated; "
        "use the Policy Benchmark tab for matched evaluation evidence."
    )

    batch_payments = (
        db.query(Payment)
        .filter(Payment.payment_id.like("sim_%"))
        .all()
    )

    rows = []

    for payment in batch_payments:

        diagnosis = (
            db.query(Diagnosis)
            .filter(
                Diagnosis.payment_id
                == payment.payment_id
            )
            .first()
        )

        actions = (
            db.query(Action)
            .filter(
                Action.payment_id
                == payment.payment_id
            )
            .all()
        )

        outcomes = (
            db.query(Outcome)
            .filter(
                Outcome.payment_id
                == payment.payment_id
            )
            .all()
        )

        rows.append(
            {
                "Payment ID": payment.payment_id,
                "Amount (Rs)": payment.amount,
                "Cause": (
                    diagnosis.cause
                    if diagnosis
                    else "unknown"
                ),
                "Actions Tried": (
                    ", ".join(
                        action.action_type
                        for action in actions
                    )
                    if actions
                    else "none"
                ),
                "Last Outcome": (
                    outcomes[-1].observed_result
                    if outcomes
                    else "pending"
                ),
                "Final Status": payment.status,
            }
        )

    df = pd.DataFrame(rows)

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Total Cases",
        len(df),
    )

    c2.metric(
        "Recovered",
        (
            (df["Final Status"] == "recovered").sum()
            if len(df)
            else 0
        ),
    )

    c3.metric(
        "Recovery Rate",
        (
            f"{(df['Final Status'] == 'recovered').mean() * 100:.1f}%"
            if len(df)
            else "0%"
        ),
    )

    st.dataframe(
        df,
        width="stretch",
        height=350,
        hide_index=True,
    )


# =====================================================
# TAB 3: HUMAN REVIEW
# =====================================================

with tab_review:

    st.caption(
        "Cases waiting for a human decision. "
        "Choose an action yourself - it doesn't have to "
        "match the ML recommendation."
    )

    pending = (
        db.query(Action)
        .filter(
            Action.decision_type
            == DecisionType.human_review,
            Action.review_status
            == ReviewStatus.pending,
        )
        .all()
    )

    if not pending:

        st.info(
            "No cases currently pending human review."
        )

    else:

        for action_row in pending:

            payment = (
                db.query(Payment)
                .filter(
                    Payment.payment_id
                    == action_row.payment_id
                )
                .first()
            )

            if not payment:
                continue

            with st.container(border=True):

                st.markdown(
                    f"**Payment:** {payment.payment_id}  |  "
                    f"**Amount:** Rs.{payment.amount:,.2f}"
                )

                preds = (
                    db.query(MLPrediction)
                    .filter(
                        MLPrediction.payment_id
                        == payment.payment_id
                    )
                    .order_by(
                        MLPrediction.predicted_at.desc()
                    )
                    .limit(3)
                    .all()
                )

                if preds and action_row.action_type != "manual_assessment":

                    pred_text = "  |  ".join(
                        f"{p.action_type}: "
                        f"{p.probability:.0%}"
                        for p in preds
                    )

                    st.write(
                        f"**ML predictions:** {pred_text}"
                    )

                st.write(
                    f"**Recommendation:** "
                    f"{'Manual assessment required; no ML recommendation' if action_row.action_type == 'manual_assessment' else action_row.action_type}  |  "
                    f"**Why escalated:** "
                    f"{action_row.reason}"
                )

                remaining = (
                    action_row.review_deadline
                    - datetime.utcnow()
                    if action_row.review_deadline
                    else None
                )

                if (
                    remaining
                    and remaining.total_seconds() > 0
                ):

                    st.caption(
                        "Deadline: "
                        f"{remaining.total_seconds() / 3600:.1f}h remaining"
                    )

                else:

                    st.caption(
                        "⚠️ Deadline has passed"
                    )

                col1, col2 = st.columns([2, 1])

                with col1:

                    chosen = st.selectbox(
                        "Choose the action to execute",
                        options=[
                            "retry",
                            "payment_link",
                            "alt_method",
                        ],
                        index=[
                            "retry",
                            "payment_link",
                            "alt_method",
                        ].index(action_row.action_type)
                        if action_row.action_type in ["retry", "payment_link", "alt_method"] else None,
                        key=f"choice_{action_row.id}",
                    )

                with col2:

                    st.write("")
                    st.write("")

                    if st.button(
                        "Approve & Execute",
                        key=f"approve_{action_row.id}",
                        disabled=chosen is None,
                    ):

                        result = human_review_action(
                            db,
                            payment.payment_id,
                            chosen,
                        )

                        if result["success"]:

                            st.success(
                                f"Executed "
                                f"{result['executed_action']}: "
                                f"{result['razorpay_payload']}"
                            )

                            st.rerun()

                        else:

                            st.error(
                                result["reason"]
                            )

    st.divider()

    st.subheader(
        "Recently Approved (this session)"
    )

    recently_approved = (
        db.query(Action)
        .filter(
            Action.decision_type
            == DecisionType.human_review,
            Action.review_status
            == ReviewStatus.actioned,
        )
        .order_by(
            Action.chosen_at.desc()
        )
        .limit(5)
        .all()
    )

    if not recently_approved:

        st.caption(
            "No approvals yet this session."
        )

    else:

        for action in recently_approved:

            audit_entry = (
                db.query(AuditLog)
                .filter(
                    AuditLog.payment_id
                    == action.payment_id,
                    AuditLog.event_type
                    == "human_approved_executed",
                )
                .order_by(
                    AuditLog.timestamp.desc()
                )
                .first()
            )

            with st.container(border=True):

                st.write(
                    f"**{action.payment_id}** — "
                    f"human-approved: "
                    f"**{action.action_type}**"
                )

                if audit_entry:

                    st.code(
                        audit_entry.payload_json,
                        language="json",
                    )


# =====================================================
# TAB 4: GUARDRAILS
# =====================================================

with tab_guardrails:

    guardrails = [
        (
            "Max retry attempts per case",
            f"{settings.max_retry_attempts} attempts",
            True,
        ),
        (
            "Cooling-off period between retries",
            f"{settings.retry_cooling_off_hours} hours",
            True,
        ),
        (
            "Maximum recovery window per case",
            f"{settings.max_recovery_window_days} days",
            True,
        ),
        (
            "Near-tie review margin (business policy)",
            f"{settings.min_action_margin_ratio:.1%} of payment amount; not statistical confidence",
            True,
        ),
        (
            "Human review high-value threshold",
            f"Rs.{settings.human_review_amount_threshold:,.0f}",
            True,
        ),
        (
            "Human review approval deadline",
            f"{settings.human_review_timeout_hours} hours",
            True,
        ),
        (
            "Human-review timeout never auto-executes",
            "enforced in code",
            True,
        ),
        (
            "Razorpay non-retryable states respected",
            "captured, authorized, halted",
            True,
        ),
        (
            "Duplicate-attempt prevention",
            "tried actions excluded from re-scoring",
            True,
        ),
        (
            "Operator-recorded fraud concern stop",
            "persistent stop; no automatic fraud detector",
            True,
        ),
    ]

    c1, c2 = st.columns(2)

    for i, (rule, value, ok) in enumerate(
        guardrails
    ):

        col = c1 if i % 2 == 0 else c2

        col.write(
            f"{'✅' if ok else '⚠️'} "
            f"**{rule}** — {value}"
        )


# =====================================================
# TAB 5: IMPACT
# =====================================================

with tab_impact:
    render_policy_benchmark()


# =====================================================
# TAB 6: DECISION EXPLANATION
# =====================================================

with tab_explain:

    # -------------------------------------------------
    # PAYMENT SELECTOR
    # -------------------------------------------------

    available_payments = (
        db.query(Payment)
        .order_by(Payment.created_at.desc())
        .all()
    )

    payment_options = {
        f"{p.payment_id} — Rs.{p.amount:,.2f} — {p.status}": p.payment_id
        for p in available_payments
    }

    if not payment_options:
        st.info(
            "No payment cases are available for decision explanation."
        )
        search_id = None

    else:
        selected_label = st.selectbox(
            "Select a payment to inspect",
            options=list(payment_options.keys()),
        )

        search_id = payment_options[selected_label]

    if search_id:

        payment = (
            db.query(Payment)
            .filter(
                Payment.payment_id == search_id
            )
            .first()
        )

        if not payment:

            st.error(
                f"No payment found with ID: {search_id}"
            )

        else:

            is_real = search_id.startswith(
                "pay_"
            )

            st.markdown(
                "### "
                + (
                    "🔴 REAL RAZORPAY TEST-MODE PAYMENT"
                    if is_real
                    else "🟡 SYNTHETIC / SIMULATED"
                )
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Amount",
                f"Rs.{payment.amount:,.2f}",
            )

            c2.metric(
                "Status",
                payment.status,
            )

            c3.metric(
                "Method",
                payment.payment_method or "-",
            )

            c4.metric(
                "Error Code",
                payment.razorpay_error_code or "-",
            )

            diagnosis = (
                db.query(Diagnosis)
                .filter(
                    Diagnosis.payment_id
                    == search_id
                )
                .first()
            )

            st.info(
                f"**Diagnosed cause:** "
                f"{diagnosis.cause if diagnosis else 'not yet diagnosed'}"
            )

            latest_decision = db.query(Action).filter_by(payment_id=search_id).order_by(
                Action.chosen_at.desc(), Action.id.desc(),
            ).first()
            assessment_required = latest_decision is not None and latest_decision.action_type == "manual_assessment"
            if assessment_required:
                st.info("Manual assessment required. No current ML probabilities or scores are available for this failure cause.")

            all_preds = [] if assessment_required else (
                db.query(MLPrediction)
                .filter(
                    MLPrediction.payment_id
                    == search_id
                )
                .order_by(
                    MLPrediction.predicted_at.desc()
                )
                .all()
            )

            latest_preds = []

            if all_preds:

                latest_time = (
                    all_preds[0].predicted_at
                )

                latest_preds = [
                    prediction
                    for prediction in all_preds
                    if prediction.predicted_at
                    == latest_time
                ]

                feature_audit = db.query(AuditLog).filter_by(
                    payment_id=search_id, event_type='decision_features', timestamp=latest_time,
                ).first()
                if feature_audit:
                    features = json.loads(feature_audit.payload_json)
                    if features.get('uses_default_history'):
                        st.caption('Recorded model input: no verified finalized customer history; neutral past-rate assumption 50%.')
                    else:
                        st.caption(f"Recorded model input: {features['history_cases']} finalized customer cases; "
                                   f"historical recovery rate {features['past_rate']:.1%}. Selected case excluded.")
                    st.caption(f"Executed attempts used by the model: {features['executed_attempts']}.")
                else:
                    st.caption('This older decision has no recorded feature snapshot; its exact history inputs are unavailable.')

                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Action": prediction.action_type,
                                "Probability": (
                                    f"{prediction.probability:.2%}"
                                ),
                            }
                            for prediction in latest_preds
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )

            all_scores = [] if assessment_required else (
                db.query(RecoveryScore)
                .filter(
                    RecoveryScore.payment_id
                    == search_id
                )
                .order_by(
                    RecoveryScore.evaluated_at.desc()
                )
                .all()
            )

            if all_scores:

                latest_score_time = (
                    all_scores[0].evaluated_at
                )

                latest_scores = [
                    score
                    for score in all_scores
                    if score.evaluated_at
                    == latest_score_time
                ]

                score_rows = []

                for score in latest_scores:

                    pred = next(
                        (
                            prediction
                            for prediction in latest_preds
                            if prediction.action_type
                            == score.action_type
                        ),
                        None,
                    )

                    score_rows.append(
                        {
                            "Action": score.action_type,
                            "Eligible": (
                                "✅"
                                if score.retry_eligible
                                else "❌"
                            ),
                            "Probability": (
                                f"{pred.probability:.2%}"
                                if pred
                                else "-"
                            ),
                            "Cost": (
                                f"Rs.{score.cost_used:.2f}"
                            ),
                            "Score": (
                                f"{score.score:.2f}"
                            ),
                            "Reason": (
                                score.eligibility_reason
                            ),
                        }
                    )

                st.dataframe(
                    pd.DataFrame(score_rows),
                    width="stretch",
                    hide_index=True,
                )

            actions = (
                db.query(Action)
                .filter(
                    Action.payment_id
                    == search_id
                )
                .order_by(
                    Action.chosen_at
                )
                .all()
            )

            if actions:

                latest_action = actions[-1]

                d1, d2 = st.columns(2)

                d1.metric(
                    "Chosen Action",
                    latest_action.action_type,
                )

                d2.metric(
                    "Decision Type",
                    latest_action.decision_type.value,
                )

                st.write(
                    f"**Reason:** "
                    f"{latest_action.reason or 'not recorded'}"
                )

            outcomes = (
                db.query(Outcome)
                .filter(
                    Outcome.payment_id
                    == search_id
                )
                .order_by(
                    Outcome.observed_at
                )
                .all()
            )

            if actions:

                for i, action in enumerate(
                    actions
                ):

                    match = next(
                        (
                            outcome
                            for outcome in outcomes
                            if outcome.action_type
                            == action.action_type
                        ),
                        None,
                    )

                    result_text = (
                        match.observed_result
                        if match
                        else "pending"
                    )

                    icon = (
                        "✅"
                        if result_text == "success"
                        else (
                            "❌"
                            if result_text == "failed"
                            else "⏳"
                        )
                    )

                    st.write(
                        f"{i + 1}. "
                        f"**{action.action_type}** "
                        f"({action.decision_type.value}) "
                        f"→ {icon} {result_text}"
                    )

            st.write(
                f"**Final payment status:** "
                f"{payment.status}"
            )
            render_checkout_maintenance(db, search_id, operator_username)
            with st.expander('Case activity timeline', expanded=True):
                timeline = case_timeline(db, search_id)
                if timeline:
                    st.dataframe(pd.DataFrame(timeline), width='stretch', hide_index=True,
                                 alt='Chronological recovery case events with safe provider references')
                    st.caption('Up to 200 latest recorded events, shown in time order. Raw webhook payloads and contact details are omitted.')
                else:
                    st.info('No case activity has been recorded yet.')



# =====================================================
# CLOSE DB
# =====================================================

try:
    with tab_reconciliation:
        render_reconciliation(db, operator_username)
finally:
    db.close()
