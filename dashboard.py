"""
RecoverAI Dashboard - Streamlit app.
Organized into tabs to reduce scroll clutter.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from app.config import settings
from app.db.session import SessionLocal
from app.models.models import Payment, Diagnosis, Action, Outcome, DecisionType, ReviewStatus, AuditLog, MLPrediction, RecoveryScore
from app.services.execution import human_review_action
from app.services.reporting import compute_impact_metrics, compute_naive_blanket_retry_baseline

st.set_page_config(page_title="RecoverAI Dashboard", layout="wide")
st.title("RecoverAI — Recovery Dashboard")

db = SessionLocal()

tab_live, tab_batch, tab_review, tab_guardrails, tab_impact, tab_explain = st.tabs(
    ["Live Razorpay Cases", "Batch Evaluation", "Human Review", "Guardrails", "Impact", "Decision Explanation"]
)


# =====================================================
# TAB 1: Live Razorpay Cases
# =====================================================
with tab_live:
    st.caption("Real Razorpay test-mode payments processed through RecoverAI.")

    live_payments = db.query(Payment).filter(Payment.payment_id.like("pay_%")).all()

    if not live_payments:
        st.info("No real Razorpay payments processed yet.")
    else:
        rows = []
        for p in live_payments:
            diagnosis = db.query(Diagnosis).filter(Diagnosis.payment_id == p.payment_id).first()
            actions = db.query(Action).filter(Action.payment_id == p.payment_id).all()
            outcomes = db.query(Outcome).filter(Outcome.payment_id == p.payment_id).all()
            rows.append({
                "Payment ID": p.payment_id,
                "Amount (Rs)": p.amount,
                "Cause": diagnosis.cause if diagnosis else "unknown",
                "Actions Tried": ", ".join(a.action_type for a in actions) or "none",
                "Decision Type": actions[-1].decision_type.value if actions else "-",
                "Last Outcome": outcomes[-1].observed_result if outcomes else "pending",
                "Final Status": p.status,
            })
        st.dataframe(pd.DataFrame(rows), width="stretch")


# =====================================================
# TAB 2: Batch Evaluation (synthetic)
# =====================================================
with tab_batch:
    st.caption("75-payment synthetic simulation - decision logic is real, outcomes are simulated.")

    batch_payments = db.query(Payment).filter(Payment.payment_id.like("sim_%")).all()
    rows = []
    for p in batch_payments:
        diagnosis = db.query(Diagnosis).filter(Diagnosis.payment_id == p.payment_id).first()
        actions = db.query(Action).filter(Action.payment_id == p.payment_id).all()
        outcomes = db.query(Outcome).filter(Outcome.payment_id == p.payment_id).all()
        rows.append({
            "Payment ID": p.payment_id,
            "Amount (Rs)": p.amount,
            "Cause": diagnosis.cause if diagnosis else "unknown",
            "Actions Tried": ", ".join(a.action_type for a in actions) or "none",
            "Last Outcome": outcomes[-1].observed_result if outcomes else "pending",
            "Final Status": p.status,
        })
    df = pd.DataFrame(rows)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Cases", len(df))
    c2.metric("Recovered", (df["Final Status"] == "recovered").sum() if len(df) else 0)
    c3.metric("Recovery Rate", f"{(df['Final Status'] == 'recovered').mean()*100:.1f}%" if len(df) else "0%")

    st.dataframe(df, width="stretch", height=350)


# =====================================================
# TAB 3: Human Review (INTERACTIVE)
# =====================================================
with tab_review:
    st.caption("Cases waiting for a human decision. Choose an action yourself - it doesn't have to match the ML recommendation.")

    pending = (
        db.query(Action)
        .filter(Action.decision_type == DecisionType.human_review, Action.review_status == ReviewStatus.pending)
        .all()
    )

    if not pending:
        st.info("No cases currently pending human review.")
    else:
        for action_row in pending:
            payment = db.query(Payment).filter(Payment.payment_id == action_row.payment_id).first()
            if not payment:
                continue

            with st.container(border=True):
                st.markdown(f"**Payment:** {payment.payment_id}  |  **Amount:** Rs.{payment.amount:,.2f}")

                preds = (
                    db.query(MLPrediction)
                    .filter(MLPrediction.payment_id == payment.payment_id)
                    .order_by(MLPrediction.predicted_at.desc())
                    .limit(3)
                    .all()
                )
                if preds:
                    pred_text = "  |  ".join(f"{p.action_type}: {p.probability:.0%}" for p in preds)
                    st.write(f"**ML predictions:** {pred_text}")

                st.write(f"**ML's recommendation:** {action_row.action_type}  |  **Why escalated:** {action_row.reason}")

                remaining = action_row.review_deadline - datetime.utcnow() if action_row.review_deadline else None
                if remaining and remaining.total_seconds() > 0:
                    st.caption(f"Deadline: {remaining.total_seconds()/3600:.1f}h remaining")
                else:
                    st.caption("⚠️ Deadline has passed")

                col1, col2 = st.columns([2, 1])
                with col1:
                    chosen = st.selectbox(
                        "Choose the action to execute",
                        options=["retry", "payment_link", "alt_method"],
                        index=["retry", "payment_link", "alt_method"].index(action_row.action_type),
                        key=f"choice_{action_row.id}",
                    )
                with col2:
                    st.write("")
                    st.write("")
                    if st.button("Approve & Execute", key=f"approve_{action_row.id}"):
                        result = human_review_action(db, payment.payment_id, chosen)
                        if result["success"]:
                            st.success(f"Executed {result['executed_action']}: {result['razorpay_payload']}")
                            st.rerun()
                        else:
                            st.error(result["reason"])
    st.divider()
    st.subheader("Recently Approved (this session)")

    recently_approved = (
        db.query(Action)
        .filter(Action.decision_type == DecisionType.human_review, Action.review_status == ReviewStatus.actioned)
        .order_by(Action.chosen_at.desc())
        .limit(5)
        .all()
    )

    if not recently_approved:
        st.caption("No approvals yet this session.")
    else:
        for a in recently_approved:
            audit_entry = (
                db.query(AuditLog)
                .filter(AuditLog.payment_id == a.payment_id, AuditLog.event_type == "human_approved_executed")
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            with st.container(border=True):
                st.write(f"**{a.payment_id}** — human-approved: **{a.action_type}**")
                if audit_entry:
                    st.code(audit_entry.payload_json, language="json")  


# =====================================================
# TAB 4: Guardrails
# =====================================================
with tab_guardrails:
    guardrails = [
        ("Max retry attempts per case", f"{settings.max_retry_attempts} attempts", True),
        ("Cooling-off period between retries", f"{settings.retry_cooling_off_hours} hours", True),
        ("Maximum recovery window per case", f"{settings.max_recovery_window_days} days", True),
        ("Human review confidence band", f"{settings.confidence_band_low}-{settings.confidence_band_high}", True),
        ("Human review high-value threshold", f"Rs.{settings.human_review_amount_threshold:,.0f}", True),
        ("Human review approval deadline", f"{settings.human_review_timeout_hours} hours", True),
        ("Human-review timeout never auto-executes", "enforced in code", True),
        ("Razorpay non-retryable states respected", "captured, authorized, halted", True),
        ("Duplicate-attempt prevention", "tried actions excluded from re-scoring", True),
        ("Fraud-flag immediate stop", "NOT YET IMPLEMENTED", False),
    ]
    c1, c2 = st.columns(2)
    for i, (rule, value, ok) in enumerate(guardrails):
        col = c1 if i % 2 == 0 else c2
        col.write(f"{'✅' if ok else '⚠️'} **{rule}** — {value}")


# =====================================================
# TAB 5: Impact
# =====================================================
with tab_impact:
    recoverai = compute_impact_metrics(db)
    baseline = compute_naive_blanket_retry_baseline(db)

    c1, c2 = st.columns(2)
    c1.metric("Total Recovered (RecoverAI)", f"Rs.{recoverai['total_recovered']:,.2f}",
               delta=f"Rs.{recoverai['total_recovered']-baseline['total_recovered']:,.2f} vs baseline")
    c2.metric("Recovery Rate", f"{recoverai['recovery_rate']*100:.1f}%",
               delta=f"{(recoverai['recovery_rate']-baseline['recovery_rate'])*100:.1f} pts vs baseline")

    chart_df = pd.DataFrame({
        "Approach": ["Naive Blanket-Retry", "RecoverAI"],
        "Recovery Rate (%)": [baseline["recovery_rate"]*100, recoverai["recovery_rate"]*100],
    })
    st.bar_chart(chart_df.set_index("Approach"))


# =====================================================
# TAB 6: Decision Explanation (search-based, unchanged logic)
# =====================================================
with tab_explain:
    search_id = st.text_input("Payment ID", placeholder="e.g. pay_TWeYgGZ8AoeDmt or sim_0014_...")

    if search_id:
        payment = db.query(Payment).filter(Payment.payment_id == search_id).first()
        if not payment:
            st.error(f"No payment found with ID: {search_id}")
        else:
            is_real = search_id.startswith("pay_")
            st.markdown(f"### {'🔴 REAL RAZORPAY TEST-MODE PAYMENT' if is_real else '🟡 SYNTHETIC / SIMULATED'}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Amount", f"Rs.{payment.amount:,.2f}")
            c2.metric("Status", payment.status)
            c3.metric("Method", payment.payment_method or "-")
            c4.metric("Error Code", payment.razorpay_error_code or "-")

            diagnosis = db.query(Diagnosis).filter(Diagnosis.payment_id == search_id).first()
            st.info(f"**Diagnosed cause:** {diagnosis.cause if diagnosis else 'not yet diagnosed'}")

            all_preds = db.query(MLPrediction).filter(MLPrediction.payment_id == search_id).order_by(MLPrediction.predicted_at.desc()).all()
            if all_preds:
                latest_time = all_preds[0].predicted_at
                latest_preds = [p for p in all_preds if p.predicted_at == latest_time]
                st.dataframe(pd.DataFrame([{"Action": p.action_type, "Probability": f"{p.probability:.2%}"} for p in latest_preds]),
                             width="stretch", hide_index=True)

            all_scores = db.query(RecoveryScore).filter(RecoveryScore.payment_id == search_id).order_by(RecoveryScore.evaluated_at.desc()).all()
            if all_scores:
                latest_score_time = all_scores[0].evaluated_at
                latest_scores = [s for s in all_scores if s.evaluated_at == latest_score_time]
                score_rows = []
                for s in latest_scores:
                    pred = next((p for p in latest_preds if p.action_type == s.action_type), None)
                    score_rows.append({
                        "Action": s.action_type, "Eligible": "✅" if s.retry_eligible else "❌",
                        "Probability": f"{pred.probability:.2%}" if pred else "-",
                        "Cost": f"Rs.{s.cost_used:.2f}", "Score": f"{s.score:.2f}", "Reason": s.eligibility_reason,
                    })
                st.dataframe(pd.DataFrame(score_rows), width="stretch", hide_index=True)

            actions = db.query(Action).filter(Action.payment_id == search_id).order_by(Action.chosen_at).all()
            if actions:
                latest_action = actions[-1]
                d1, d2 = st.columns(2)
                d1.metric("Chosen Action", latest_action.action_type)
                d2.metric("Decision Type", latest_action.decision_type.value)
                st.write(f"**Reason:** {latest_action.reason or 'not recorded'}")

            outcomes = db.query(Outcome).filter(Outcome.payment_id == search_id).order_by(Outcome.observed_at).all()
            if actions:
                for i, a in enumerate(actions):
                    match = next((o for o in outcomes if o.action_type == a.action_type), None)
                    result_text = match.observed_result if match else "pending"
                    icon = "✅" if result_text == "success" else ("❌" if result_text == "failed" else "⏳")
                    st.write(f"{i+1}. **{a.action_type}** ({a.decision_type.value}) → {icon} {result_text}")
            st.write(f"**Final payment status:** {payment.status}")

db.close()