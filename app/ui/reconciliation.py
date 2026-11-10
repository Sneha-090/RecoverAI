"""Operator review controls; provider reads occur only on an explicit click."""

import streamlit as st

from app.models.models import WebhookInbox
from app.services.reconciliation import (list_stuck_cases, reconciliation_references,
    check_reconciliation_status, reconcile_verified_success, ReconciliationError, return_verified_failure_to_review, resume_unattempted_retry)


def render_reconciliation(db, operator_username):
    st.subheader("Stuck cases")
    st.caption("Check an existing Razorpay payment, then settle a verified success. This screen does not create orders or payment links.")
    flash = st.session_state.pop("reconciliation_flash", None)
    if flash:
        st.success(flash)
    cases = list_stuck_cases(db)
    if not cases:
        st.info("No recovery cases currently need reconciliation.")
    else:
        case_map = {row["payment_id"]: row for row in cases}
        payment_id = st.selectbox("Case to review", list(case_map), key="reconciliation_case",
            format_func=lambda value: f"{value} — Rs.{case_map[value]['amount']:,.2f}")
        # Validate widget values again; client-side choices are not authorization.
        if payment_id not in case_map:
            st.error("Select a valid case.")
            return
        case = case_map[payment_id]
        active = case["state"] == "processing"
        with st.container(border=True):
            st.write("**Status:** " + ("May still be running" if active else "Needs verification"))
            st.caption(f"Last update: {case['updated_at']} UTC")
            if active:
                st.warning("This case may still be running. You can check its status, but this screen will not reset its active operation.")
            refs = reconciliation_references(db, payment_id)
            ref_map = {row["key"]: row for row in refs}
            if not refs:
                st.warning("No saved recovery reference is available. Investigate the payment in Razorpay; this case will remain blocked.")
            else:
                key = st.selectbox("Recovery attempt", list(ref_map), key=f"reconciliation_reference_{payment_id}",
                    format_func=lambda value: ref_map[value]["provider_id"] or "Creation response missing — verify a Razorpay reference")
                if key not in ref_map:
                    st.error("Select a valid recovery attempt.")
                    return
                reference = ref_map[key]
                supplied = None
                if not reference["provider_id"]:
                    label = "Razorpay order ID" if reference["kind"] == "order" else "Razorpay payment link ID"
                    supplied = st.text_input(label, key=f"reconciliation_provider_{key}", max_chars=128).strip()
                    st.caption("Use the existing resource from Razorpay. Its recovery reference, amount and currency must match this case.")
                identity = (payment_id, key, supplied)
                if st.button("Check Razorpay status", key="reconciliation_check", icon=":material/search:"):
                    try:
                        evidence = check_reconciliation_status(db, payment_id, key, supplied)
                        st.session_state["reconciliation_evidence"] = {"identity": identity, "evidence": evidence}
                    except ReconciliationError as exc:
                        st.session_state.pop("reconciliation_evidence", None)
                        st.error(str(exc))
                    except Exception:
                        st.session_state.pop("reconciliation_evidence", None)
                        st.error("Razorpay verification is unavailable. The case remains blocked; try the status check again later.")
                checked = st.session_state.get("reconciliation_evidence", {})
                if checked.get("identity") == identity:
                    evidence = checked["evidence"]
                    st.caption(f"Checked: {evidence['checked_at']} · {evidence['provider_id']}")
                    verified = evidence["result"] == "success"
                    if verified:
                        st.success("Full payment verified with matching amount and currency.")
                    elif evidence["result"] == "pending":
                        st.info("Payment is still pending. The case remains blocked.")
                    else:
                        st.warning("No successful recovery was found. The case remains blocked.")
                    if evidence['result'] == 'pending' and reference['kind'] == 'order':
                        st.caption('Resume only one saved first retry after fresh checks prove it is unpaid, never attempted and the original order is open. No new order is created.')
                        if st.button('Resume verified unattempted retry', key='reconciliation_resume_unattempted', disabled=active):
                            result = resume_unattempted_retry(db, payment_id, key, operator_username)
                            st.session_state.pop('reconciliation_evidence', None)
                            if result['status'] == 'awaiting_outcome':
                                st.session_state['reconciliation_flash'] = 'Existing unattempted retry is active again. No new order or payment was created.'
                                st.rerun()
                            else:
                                st.warning(result['reason'])
                    if evidence['result']=='failed':
                        st.caption('Re-check all known executions and the original order, then return a verified failure to manual review. This control cannot create a checkout or authorize an automatic retry.')
                        if st.button('Return verified failure to manual review',key='reconciliation_failed_review',disabled=active):
                            result=return_verified_failure_to_review(db,payment_id,key,operator_username)
                            st.session_state.pop('reconciliation_evidence',None)
                            if result['status']=='pending_review':
                                st.session_state['reconciliation_flash']='Verified failure recorded. Case returned to manual review; no new payment request was sent.'
                                st.rerun()
                            else:st.warning(result['reason'])
                    if st.button("Mark case recovered", key="reconciliation_settle", type="primary",
                                 disabled=active or not verified):
                        result = reconcile_verified_success(db, payment_id, key, operator_username, supplied)
                        st.session_state.pop("reconciliation_evidence", None)
                        if result["status"] == "recovered":
                            st.session_state["reconciliation_flash"] = "Verified recovery recorded. No new payment request was sent."
                            st.rerun()
                        else:
                            st.warning(result["reason"])
    st.divider()
    st.subheader("Events needing investigation")
    events = db.query(WebhookInbox).filter(WebhookInbox.state == "needs_reconciliation").order_by(
        WebhookInbox.created_at, WebhookInbox.event_id).limit(50).all()
    if events:
        st.dataframe([{"Event ID": row.event_id, "Attempts": row.attempts,
                       "Received (UTC)": row.created_at.isoformat()} for row in events],
                     hide_index=True, alt="Webhook events retained for manual investigation")
        st.caption("These events stay saved. Settling a case does not force replay of an uncertain event.")
    else:
        st.caption("No webhook events are currently held for manual investigation.")
