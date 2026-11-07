from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Action, Payment, RecoveryIntent, RecoveryReservation, AuditLog
from app.services.order_service import create_payment_link
from app.services.execution import execute_action, human_review_action, _check_real_outcome
from app.services.reconciliation import reconcile_verified_success
from scripts.demo_provider import DemoProvider


@pytest.mark.parametrize('failed', ['card','upi','wallet','netbanking'])
def test_alternate_checkout_hides_failed_method_and_never_sends_messages(monkeypatch, failed):
    create = Mock(return_value={'id':'plink_alt'})
    monkeypatch.setattr('app.services.order_service.client.payment_link.create', create)
    create_payment_link(499, 'Alternate method', intent_id='intent', exclude_method=failed)
    request = create.call_args.args[0]
    methods = request['options']['checkout']['method']
    assert set(methods) == {'card','upi','wallet','netbanking'}
    assert methods[failed] is False and sum(methods.values()) == 3
    assert request['notes'] == {'recoverai_intent_id':'intent','recoverai_excluded_method':failed}
    assert request['notify'] == {'sms':False,'email':False}
    assert request['reminder_enable'] is False
    assert request['accept_partial'] is False


def test_unknown_original_method_does_not_create_a_fake_alternative(monkeypatch):
    create = Mock()
    monkeypatch.setattr('app.services.order_service.client.payment_link.create', create)
    with pytest.raises(ValueError):
        create_payment_link(499, 'Alternate method', exclude_method='unknown')
    create.assert_not_called()


@pytest.fixture
def alt_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Payment(payment_id='pay_alt', amount=499, status='failed', razorpay_state='failed',
                       payment_method='card', razorpay_error_reason='insufficient_funds'))
        db.commit()
        yield db
    engine.dispose()


def test_missing_method_is_excluded_from_scoring_and_approval(alt_db, monkeypatch):
    payment = alt_db.get(Payment,'pay_alt'); payment.payment_method = None; alt_db.commit()
    monkeypatch.setattr('app.services.decision.predict_all_actions', lambda *args: {'retry':.1,'payment_link':.8,'alt_method':.99})
    create = Mock(return_value={'id':'plink_general'})
    monkeypatch.setattr('app.services.execution.create_payment_link', create)
    assert execute_action(alt_db, payment)['chosen_action'] == 'payment_link'
    # A separate pending assessment cannot bypass the missing original method.
    from datetime import datetime,timedelta
    alt_db.add(Payment(payment_id='pay_review_alt', amount=499, status='failed'))
    alt_db.add(Action(payment_id='pay_review_alt', action_type='manual_assessment',
                      decision_type='human_review',review_status='pending',review_deadline=datetime.utcnow()+timedelta(hours=1)))
    alt_db.commit()
    assert human_review_action(alt_db,'pay_review_alt','alt_method')['success'] is False
    assert create.call_count == 1


@pytest.mark.parametrize('method,valid', [('upi',True),('card',False),(None,False)])
def test_paid_link_requires_verified_capture_with_different_method(monkeypatch, method, valid):
    link = {'id':'plink_alt','status':'paid','amount':49900,'amount_paid':49900,'currency':'INR',
            'payments':[{'payment_id':'pay_capture'}]}
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch', lambda _:link)
    monkeypatch.setattr('app.services.execution.client.payment.fetch', lambda _: {
        'id':'pay_capture','status':'captured','amount':49900,'currency':'INR','method':method})
    payload = {'type':'payment_link','payment_link_id':'plink_alt','expected_amount_paise':49900,
               'expected_currency':'INR','excluded_method':'card','available_methods':['upi','wallet','netbanking']}
    if valid:
        assert _check_real_outcome(payload) == 'success'
    else:
        with pytest.raises(ValueError):
            _check_real_outcome(payload)


def test_lost_response_preserves_alternate_policy_through_reconciliation(alt_db, monkeypatch):
    fake = DemoProvider(); fake.lose_next_response = True
    monkeypatch.setattr('app.services.order_service.client.payment_link.create',fake.create_link)
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch',fake.fetch_link)
    monkeypatch.setattr('app.services.execution.client.payment.fetch',fake.fetch_payment)
    with pytest.raises(TimeoutError):
        execute_action(alt_db,alt_db.get(Payment,'pay_alt'))
    intent = alt_db.query(RecoveryIntent).one()
    assert alt_db.get(RecoveryReservation,'pay_alt').state == 'needs_reconciliation'
    fake.capture(fake.last_created)
    result = reconcile_verified_success(alt_db,'pay_alt','intent:'+intent.id,'operator',fake.last_created[1])
    assert result['status'] == 'recovered'
    import json
    payload = json.loads(alt_db.query(AuditLog).filter_by(event_type='executed').one().payload_json)
    assert payload['excluded_method'] == 'card' and 'card' not in payload['available_methods']
    assert fake.creations == 1
