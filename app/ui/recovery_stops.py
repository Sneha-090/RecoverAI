"""Authenticated operator stop controls; no provider calls on render."""
import streamlit as st
from app.models.models import Payment
from app.services.recovery_stops import REASONS,stop_followup


def render_recovery_stop(db,operator):
    flash=st.session_state.pop('stop_followup_flash',None)
    if flash:st.info(flash)
    cases=db.query(Payment).filter(Payment.payment_id.startswith('pay_',autoescape=True),
                                  Payment.status=='failed').order_by(Payment.created_at.desc()).limit(200).all()
    if not cases:return
    with st.expander('Stop further recovery'):
        choices={p.payment_id:p for p in cases}
        selected=st.selectbox('Payment case',list(choices),key='stop_followup_case')
        reason=st.selectbox('Stop reason',list(REASONS),format_func=REASONS.get,key='stop_followup_reason')
        st.caption('Stops future collection for all known attempts on the same original order. An in-flight request can still finish, and previously shared links may still accept payment. Use old-link cleanup separately. This does not cancel a payment or issue a refund.')
        if st.button('Stop further recovery',key='stop_followup_submit',icon=':material/block:'):
            if selected not in choices or reason not in REASONS:
                st.error('Select a valid case and stop reason.');return
            try:
                result=stop_followup(db,selected,operator,reason)
                st.session_state['stop_followup_flash']=result['message']
                st.rerun()
            except Exception:
                db.rollback()
                st.error('Stop could not be confirmed. Check the case before taking another action.')
