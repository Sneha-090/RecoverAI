import json
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.models.models import Payment,Action,AuditLog,RecoveryReservation
from app.services.execution_records import record_execution
from app.services.operator_checkout import operator_checkout_config,CheckoutUnavailable
from app.ui.operator_checkout import checkout_html


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:yield session
    engine.dispose()


def order(**changes):
    return {'id':'order_Test','amount':49900,'currency':'INR','status':'created',
            'amount_paid':0,'amount_due':49900,'attempts':0,**changes}


def test_original_preview_is_read_only_and_contains_only_public_configuration(db,monkeypatch):
    fetch=Mock(return_value=order())
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',fetch)
    config=operator_checkout_config(db,'order_Test')
    assert config['amount_paise']==49900 and config['key_id'].startswith('rzp_test_')
    assert set(config)=={'key_id','order_id','amount_paise','currency','checkout_note'}
    assert db.query(Payment).count()==db.query(Action).count()==0


@pytest.mark.parametrize('changes',[{'id':'order_Other'},{'amount':True},{'currency':'USD'},
    {'status':'paid'},{'amount_paid':1},{'amount_paid':False},{'amount_due':1},{'attempts':-1}])
def test_invalid_or_paid_order_cannot_open_preview(db,monkeypatch,changes):
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',lambda _:order(**changes))
    with pytest.raises(CheckoutUnavailable):operator_checkout_config(db,'order_Test')


def test_original_checkout_cannot_collect_again_after_recovery(db,monkeypatch):
    db.add(Payment(payment_id='pay_done',order_id='order_Test',amount=499,status='recovered'));db.commit()
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',lambda _:order())
    with pytest.raises(CheckoutUnavailable,match='stopped or recovery'):operator_checkout_config(db,'order_Test')


def test_issued_recovery_order_must_match_expected_amount_and_active_claim(db,monkeypatch):
    payment=Payment(payment_id='pay_pending',amount=499,status='failed')
    action=Action(payment_id='pay_pending',action_type='retry',decision_type='auto')
    audit=AuditLog(payment_id='pay_pending',event_type='executed',payload_json=json.dumps({'type':'order','order_id':'order_Test'}))
    db.add_all([payment,action,audit]);db.flush()
    record_execution(db,payment,action,audit,json.loads(audit.payload_json))
    db.add(RecoveryReservation(payment_id='pay_pending',owner='waiting',state='awaiting_outcome'));db.commit()
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',lambda _:order())
    assert operator_checkout_config(db,'order_Test')['amount_paise']==49900
    payment.recovery_stop_reason='customer_opt_out';db.commit()
    with pytest.raises(CheckoutUnavailable):operator_checkout_config(db,'order_Test')


def test_iframe_escapes_script_input_and_drops_nonpublic_fields():
    config={'key_id':'rzp_test_</script><script>PRIVATE()</script>','order_id':'order_EXPIRES','amount_paise':49900,
            'currency':'INR','secret':'DO_NOT_RENDER','operator_password_hash':'DO_NOT_RENDER'}
    html=checkout_html(config,12345)
    assert 'DO_NOT_RENDER' not in html
    assert '<script>PRIVATE()' not in html
    assert 'order_EXPIRES' in html and 'const expires=12345' in html
    assert 'checkout.open();' in html and 'button.onclick=' in html
    assert 'no-referrer' in html and 'fetch(' not in html
