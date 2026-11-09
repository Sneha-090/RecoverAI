"""Test-only checkout inside the existing authenticated operator session."""
import json
import time
import streamlit as st
from app.services.operator_checkout import operator_checkout_config,CheckoutUnavailable


def checkout_html(config,expires_at):
    # Only explicitly selected public configuration enters HTML. Never secrets/contacts.
    public={key:config[key] for key in ('key_id','order_id','amount_paise','currency')}
    encoded=json.dumps(public,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta name="color-scheme" content="light dark">
<title>Operator Test Mode checkout</title></head><body>
<p>Razorpay Test Mode. No real money. Payment requires an explicit click.</p>
<button id="pay" type="button">Start Test Mode payment</button><p id="result" role="status"></p>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script><script>
const config=CONFIG; const expires=EXPIRES; const button=document.getElementById('pay');
const result=document.getElementById('result');
button.onclick=()=>{if(Date.now()/1000>expires){button.disabled=true;result.textContent='Checkout preview expired. Load it again in the dashboard.';return;}
if(!config.key_id.startsWith('rzp_test_')){button.disabled=true;return;}
button.disabled=true;
const checkout=new Razorpay({key:config.key_id,order_id:config.order_id,amount:config.amount_paise,currency:config.currency,
timeout:180,remember_customer:false,
handler:(response)=>{button.disabled=true;result.textContent='Test payment completed: '+response.razorpay_payment_id+'. Refresh the dashboard after signed webhook verification.';},
modal:{ondismiss:()=>{button.disabled=false;}}});
checkout.on('payment.failed',(response)=>{result.textContent='Test payment failed: '+(response.error?.metadata?.payment_id||'unavailable')+'. Signed webhook processing will update the dashboard.';});
checkout.open();};
</script></body></html>'''.replace('EXPIRES',str(int(expires_at))).replace('CONFIG',encoded)


def render_operator_checkout(db):
    with st.expander('Operator Test checkout',expanded=bool(st.session_state.get('operator_checkout_order'))):
        st.caption('Uses this dashboard login. Loads an existing Test Mode order after fresh provider and case checks. No order or payment is created by loading a preview.')
        order_id=st.text_input('Existing Test Mode order ID',key='operator_checkout_order',max_chars=70).strip()
        if st.button('Load Test checkout',key='operator_checkout_load'):
            st.session_state.pop('operator_checkout_preview',None)
            try:
                config=operator_checkout_config(db,order_id)
                st.session_state['operator_checkout_preview']={'config':config,'expires_at':time.time()+180}
            except CheckoutUnavailable as error:st.error(str(error))
            except Exception:st.error('Checkout verification unavailable. No payment was created; check the case before trying again.')
        preview=st.session_state.get('operator_checkout_preview')
        if preview and preview['config']['order_id']==order_id:
            if preview['expires_at']<=time.time():
                st.session_state.pop('operator_checkout_preview',None)
                st.info('Preview expired. Load the checkout again.')
            else:
                st.write(f"{preview['config']['order_id']} · INR {preview['config']['amount_paise']/100:.2f}")
                st.iframe(checkout_html(preview['config'],preview['expires_at']),height=720,
                          alt='Authenticated operator Razorpay Test Mode payment preview')
