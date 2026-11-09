"""Provider reads and cancellations require separate explicit operator clicks."""

import streamlit as st

from app.models.models import Payment,RecoveryExecution
from app.services.checkout_maintenance import check_old_link,cancel_old_link


def render_checkout_maintenance(db,payment_id,operator):
    payment=db.get(Payment,payment_id)
    if not payment or payment.status not in {'recovered','closed_unrecovered','paid_original'}:
        return
    references=db.query(RecoveryExecution).filter_by(payment_id=payment_id,provider_type='payment_link').all()
    if not references:return
    with st.expander('Old recovery links'):
        flash=st.session_state.pop('cleanup_flash_'+payment_id,None)
        if flash:st.info(flash)
        choices={row.id:row.provider_id for row in references}
        selected=st.selectbox('Recorded payment link',list(choices),format_func=choices.get,key='cleanup_link_'+payment_id)
        if selected not in choices:return
        preview_key=f'cleanup_preview_{payment_id}_{selected}'
        if st.button('Check old link status',key='cleanup_check_'+payment_id):
            st.session_state.pop(preview_key,None)
            try:st.session_state[preview_key]=check_old_link(db,payment_id,selected)
            except Exception:st.error('Provider verification is unavailable. No cancellation was sent.')
        evidence=st.session_state.get(preview_key)
        if evidence:
            st.write('Provider status: '+evidence['status'])
        st.caption('Only an unpaid link on a closed case can be cancelled. Paid and partially-paid links are left for investigation. This control does not refund payments.')
        if st.button('Cancel unpaid old link',key='cleanup_cancel_'+payment_id,
                     disabled=not evidence or not evidence['can_cancel']):
            result=cancel_old_link(db,payment_id,selected,operator)
            st.session_state.pop(preview_key,None)
            st.session_state['cleanup_flash_'+payment_id]=result['message']
            st.rerun()
