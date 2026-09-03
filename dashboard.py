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
)
from app.services.execution import human_review_action
from app.services.reporting import (
    compute_impact_metrics,
    compute_naive_blanket_retry_baseline,
)


# =====================================================
# PAGE SETUP
# =====================================================

st.set_page_config(
    page_title="RecoverAI Dashboard",
    layout="wide",
)

st.title("RecoverAI — Recovery Dashboard")

db = SessionLocal()


# =====================================================
# TOP-LEVEL RECOVERY SNAPSHOT
# =====================================================

impact_snapshot = compute_impact_metrics(db)

kpi1, kpi2, kpi3 = st.columns(3)

kpi1.metric(
    "Payments in Simulation",
    impact_snapshot["total_payments"],
)

kpi2.metric(
    "Recovered Payments",
    impact_snapshot["recovered_count"],
)

kpi3.metric(
    "Revenue Recovered",
    f"Rs.{impact_snapshot['total_recovered']:,.2f}",
)

st.caption(
    "Synthetic impact snapshot — "
    "live Razorpay cases are shown in the Live Razorpay Cases tab."
)


# =====================================================
# HELPERS
# =====================================================

def get_recovery_order_info(payment_id: str):
    """
    Find the latest RecoverAI-created recovery order for a payment.

    We inspect executed audit records and return the most recent
    order-type recovery payload.
    """
    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.payment_id == payment_id,
            AuditLog.event_type == "executed",
        )
        .order_by(AuditLog.timestamp.desc())
        .all()
    )

    for entry in entries:
        if not entry.payload_json:
            continue

        try:
            payload = json.loads(entry.payload_json)
        except (TypeError, json.JSONDecodeError):
            continue

        if (
            payload.get("type") == "order"
            and payload.get("order_id")
        ):
            return {
                "type": "order",
                "order_id": payload["order_id"],
            }

    return None


# =====================================================
# TABS
# =====================================================

(
    tab_live,
    tab_batch,
    tab_review,
    tab_guardrails,
    tab_impact,
    tab_explain,
) = st.tabs(
    [
        "Live Razorpay Cases",
        "Batch Evaluation",
        "Human Review",
        "Guardrails",
        "Impact",
        "Decision Explanation",
    ]
)


# =====================================================
# TAB 1: LIVE RAZORPAY CASES
# =====================================================

with tab_live:

    st.caption(
        "Real Razorpay test-mode payments processed through RecoverAI."
    )

    live_payments = (
        db.query(Payment)
        .filter(Payment.payment_id.like("pay_%"))
        .order_by(Payment.created_at.desc())
        .all()
    )

    if not live_payments:

        st.info(
            "No real Razorpay payments processed yet."
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
            if payment.status == "recovered":
                continue

            recovery = get_recovery_order_info(
                payment.payment_id
            )

            if (
                recovery
                and recovery["type"] == "order"
            ):

                recovery_action_found = True

                checkout_url = (
                    "http://127.0.0.1:5500/scripts/checkout.html"
                    f"?order_id={recovery['order_id']}"
                    f"&amount={payment.amount}"
                )

                st.markdown(
                    f"**{payment.payment_id}**  |  "
                    f"Rs.{payment.amount:,.2f}  |  "
                    f"[💳 Retry Payment]({checkout_url})"
                )

        if not recovery_action_found:

            st.caption(
                "No active RecoverAI retry payments available."
            )


# =====================================================
# TAB 2: BATCH EVALUATION
# =====================================================

with tab_batch:

    st.caption(
        "75-payment synthetic simulation - "
        "decision logic is real, outcomes are simulated."
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

                if preds:

                    pred_text = "  |  ".join(
                        f"{p.action_type}: "
                        f"{p.probability:.0%}"
                        for p in preds
                    )

                    st.write(
                        f"**ML predictions:** {pred_text}"
                    )

                st.write(
                    f"**ML's recommendation:** "
                    f"{action_row.action_type}  |  "
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
                        ].index(
                            action_row.action_type
                        ),
                        key=f"choice_{action_row.id}",
                    )

                with col2:

                    st.write("")
                    st.write("")

                    if st.button(
                        "Approve & Execute",
                        key=f"approve_{action_row.id}",
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
            "Human review confidence band",
            f"{settings.confidence_band_low}-"
            f"{settings.confidence_band_high}",
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
            "Fraud-flag immediate stop",
            "NOT YET IMPLEMENTED",
            False,
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

    recoverai = compute_impact_metrics(db)

    baseline = (
        compute_naive_blanket_retry_baseline(db)
    )

    c1, c2 = st.columns(2)

    c1.metric(
        "Total Recovered (RecoverAI)",
        f"Rs.{recoverai['total_recovered']:,.2f}",
        delta=(
            f"Rs."
            f"{recoverai['total_recovered'] - baseline['total_recovered']:,.2f}"
            " vs baseline"
        ),
    )

    c2.metric(
        "Recovery Rate",
        f"{recoverai['recovery_rate'] * 100:.1f}%",
        delta=(
            f"{(recoverai['recovery_rate'] - baseline['recovery_rate']) * 100:.1f}"
            " pts vs baseline"
        ),
    )

    chart_df = pd.DataFrame(
        {
            "Approach": [
                "Naive Blanket-Retry",
                "RecoverAI",
            ],
            "Recovery Rate (%)": [
                baseline["recovery_rate"] * 100,
                recoverai["recovery_rate"] * 100,
            ],
        }
    )

    st.bar_chart(
        chart_df.set_index("Approach")
    )


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

            all_preds = (
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

            all_scores = (
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


# =====================================================
# CLOSE DB
# =====================================================

db.close()