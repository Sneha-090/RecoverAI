import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from app.config import settings
from app.db.session import Base
from app.models.models import (Payment, Action, AuditLog, Outcome, RecoveryExecution,
                               RecoveryReservation, RecoveryIntent)
from app.services.execution_records import record_execution
from app.services.passwords import hash_password


REVIEW_APP = '''
from app.ui.operator_login import require_dashboard_operator
operator = require_dashboard_operator()
from app.db.session import SessionLocal
from app.ui.reconciliation import render_reconciliation
with SessionLocal() as db:
    render_reconciliation(db, operator)
'''
PASSWORD = 'review-test-password'


@pytest.fixture
def review_ui(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'review-ui.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr('app.db.session.SessionLocal', factory)
    monkeypatch.setattr(settings, 'operator_username', 'operator')
    monkeypatch.setattr(settings, 'operator_password_hash', SecretStr(hash_password(PASSWORD)))
    yield factory
    engine.dispose()


def add_case(factory, state='needs_reconciliation', intent=False):
    with factory() as db:
        payment = Payment(payment_id='pay_ui', amount=499, status='failed')
        db.add(payment)
        db.add(RecoveryReservation(payment_id=payment.payment_id, owner='old', state=state))
        if intent:
            db.add(RecoveryIntent(id='ui-intent', payment_id=payment.payment_id, action_type='payment_link', provider_type='payment_link'))
        else:
            action = Action(payment_id=payment.payment_id, action_type='payment_link', decision_type='auto', chosen_at=datetime.utcnow()-timedelta(seconds=1))
            payload = {'type': 'payment_link', 'payment_link_id': 'plink_ui'}
            audit = AuditLog(payment_id=payment.payment_id, event_type='executed', payload_json=json.dumps(payload))
            db.add_all([action, audit]); db.flush()
            record_execution(db, payment, action, audit, payload)
        db.commit()


def login(app):
    app.text_input(key='operator_login_username').set_value('operator')
    app.text_input(key='operator_login_password').set_value(PASSWORD)
    app.button[0].click().run(timeout=20)
    assert not app.exception
    return app


def mock_link(monkeypatch, result='success', notes=None):
    resource = {'id': 'plink_ui', 'status': 'paid' if result == 'success' else 'expired' if result == 'failed' else 'created',
                'amount': 49900, 'amount_paid': 49900, 'currency': 'INR', 'notes': notes or {}}
    fetch = Mock(return_value=resource)
    monkeypatch.setattr('app.services.reconciliation.client.payment_link.fetch', fetch)
    return fetch


def test_review_is_hidden_until_authenticated(review_ui, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('No database access before login'))
    monkeypatch.setattr('app.db.session.SessionLocal', forbidden)
    app = AppTest.from_string(REVIEW_APP).run(timeout=20)
    assert not app.exception
    assert not app.selectbox and not app.dataframe
    assert app.text_input(key='operator_login_password')
    forbidden.assert_not_called()


def test_no_provider_call_until_check_and_success_requires_separate_settlement(review_ui, monkeypatch):
    add_case(review_ui)
    fetch = mock_link(monkeypatch)
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    fetch.assert_not_called()
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception
    assert any('Full payment verified' in item.value for item in app.success)
    with review_ui() as db:
        assert db.get(Payment, 'pay_ui').status == 'failed'
        assert db.query(Outcome).count() == 0
    app.button(key='reconciliation_settle').click().run(timeout=20)
    assert not app.exception
    assert any('Verified recovery recorded' in item.value for item in app.success)
    with review_ui() as db:
        assert db.get(Payment, 'pay_ui').status == 'recovered'
        assert db.query(Outcome).count() == 1
        assert db.get(RecoveryReservation, 'pay_ui') is None


@pytest.mark.parametrize('result', ['pending', 'failed'])
def test_unsuccessful_provider_status_disables_settlement(review_ui, monkeypatch, result):
    add_case(review_ui)
    mock_link(monkeypatch, result)
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception
    assert app.button(key='reconciliation_settle').disabled
    with review_ui() as db:
        assert db.get(RecoveryReservation, 'pay_ui').state == 'needs_reconciliation'
        assert db.query(Outcome).count() == 0


def test_active_operation_can_be_checked_but_not_reset(review_ui, monkeypatch):
    add_case(review_ui, state='processing')
    mock_link(monkeypatch)
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception and app.button(key='reconciliation_settle').disabled
    assert any('may still be running' in item.value for item in app.warning)


def test_provider_error_is_sanitized_in_ui(review_ui, monkeypatch):
    add_case(review_ui)
    monkeypatch.setattr('app.services.reconciliation.client.payment_link.fetch', Mock(side_effect=TimeoutError('SECRET_PROVIDER_RESPONSE')))
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception
    assert any('verification is unavailable' in item.value for item in app.error)
    assert all('SECRET_PROVIDER_RESPONSE' not in item.value for item in app.error)


def test_missing_response_can_be_reviewed_using_verified_provider_reference(review_ui, monkeypatch):
    add_case(review_ui, intent=True)
    mock_link(monkeypatch, notes={'recoverai_intent_id': 'ui-intent'})
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    app.text_input(key='reconciliation_provider_intent:ui-intent').set_value('plink_ui')
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception and not app.button(key='reconciliation_settle').disabled
    app.button(key='reconciliation_settle').click().run(timeout=20)
    assert not app.exception
    with review_ui() as db:
        assert db.get(RecoveryIntent, 'ui-intent').state == 'bound'
        assert db.query(Action).count() == db.query(RecoveryExecution).count() == db.query(Outcome).count() == 1


def test_no_stuck_cases_has_clear_empty_state(review_ui):
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    assert not app.exception
    assert any('No recovery cases' in item.value for item in app.info)


def test_main_dashboard_includes_authenticated_review_tab(review_ui, monkeypatch):
    legacy = Mock(side_effect=AssertionError('Legacy model-derived baseline must not be used'))
    monkeypatch.setattr('app.services.reporting.compute_naive_blanket_retry_baseline', legacy)
    app = login(AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard.py')).run(timeout=25))
    assert not app.exception
    assert 'Recovery Review' in [tab.label for tab in app.tabs]
    assert 'Policy Benchmark' in [tab.label for tab in app.tabs]
    legacy.assert_not_called()


def test_changing_provider_reference_discards_preview(review_ui, monkeypatch):
    add_case(review_ui, intent=True)
    mock_link(monkeypatch, notes={'recoverai_intent_id': 'ui-intent'})
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    app.text_input(key='reconciliation_provider_intent:ui-intent').set_value('plink_ui')
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.button(key='reconciliation_settle').disabled
    app.text_input(key='reconciliation_provider_intent:ui-intent').set_value('plink_other').run(timeout=20)
    assert not app.exception
    assert 'reconciliation_settle' not in [button.key for button in app.button]


def test_held_events_are_read_only_and_omit_raw_payload(review_ui):
    from app.models.models import WebhookInbox
    with review_ui() as db:
        db.add(WebhookInbox(event_id='evt_manual', payload_json='PRIVATE_CONTACT',
                            state='needs_reconciliation', attempts=20))
        db.commit()
    app = login(AppTest.from_string(REVIEW_APP).run(timeout=20))
    assert not app.exception
    table = app.dataframe[0].value
    assert table['Event ID'].tolist() == ['evt_manual']
    assert 'PRIVATE_CONTACT' not in table.to_string()
    assert all('replay' not in button.label.lower() for button in app.button)



def test_unknown_cause_needs_explicit_operator_choice_before_provider_creation(review_ui, monkeypatch):
    from app.services.execution import execute_action
    from app.models.models import MLPrediction
    with review_ui() as db:
        payment = Payment(payment_id='pay_unknown_ui', amount=499, status='failed',
                          razorpay_state='failed', razorpay_error_reason='payment_failed')
        db.add(payment); db.commit()
        assert execute_action(db, payment)['chosen_action'] == 'manual_assessment'
        review_id = db.query(Action).one().id
        # Old predictions must not be presented as a new unsupported recommendation.
        db.add(MLPrediction(payment_id=payment.payment_id, action_type='retry', probability=.99))
        db.commit()
    create = Mock(return_value={'id':'plink_operator_choice','short_url':'https://example.invalid/choice'})
    monkeypatch.setattr('app.services.execution.create_payment_link', create)
    app = login(AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard.py')).run(timeout=25))
    choice = app.selectbox(key=f'choice_{review_id}')
    assert choice.value is None
    assert app.button(key=f'approve_{review_id}').disabled
    assert not any('ML predictions:' in item.value for item in app.markdown)
    assert any('No current ML probabilities' in item.value for item in app.info)
    create.assert_not_called()
    choice.select('payment_link').run(timeout=25)
    assert not app.exception and not app.button(key=f'approve_{review_id}').disabled
    app.button(key=f'approve_{review_id}').click().run(timeout=25)
    assert not app.exception
    assert create.call_count == 1
    with review_ui() as db:
        assert db.get(Action, review_id).review_status.value == 'actioned'
        assert db.query(Action).filter_by(payment_id='pay_unknown_ui', decision_type='auto').one().action_type == 'payment_link'



def test_action_distribution_filters_sources_and_top_metrics_are_test_mode_only(review_ui):
    with review_ui() as db:
        db.add_all([
            Payment(payment_id='pay_mix', order_id='order_shared', amount=499, status='recovered'),
            Payment(payment_id='pay_retry', order_id='order_shared', amount=499, status='failed'),
            Payment(payment_id='pay_direct', order_id='order_direct', amount=499, status='paid_original'),
            Payment(payment_id='sim_mix', amount=9000, status='recovered'),
        ])
        db.commit()
    app = login(AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard.py')).run(timeout=25))
    assert 'Action Distribution' in [tab.label for tab in app.tabs]
    assert app.metric[0].label == 'Test Mode orders / standalone cases' and app.metric[0].value == '2'
    assert app.metric[2].label == 'Test Mode amount recovered' and app.metric[2].value == 'Rs.499.00'
    tab = next(tab for tab in app.tabs if tab.label == 'Action Distribution')
    assert tab.metric[0].value == '3'
    assert any('1 groups paid at the original checkout' in item.value for item in app.caption)
    app.segmented_control(key='action_distribution_scope').set_value('Simulation').run(timeout=25)
    assert not app.exception
    assert app.metric[2].value == 'Rs.499.00'
    assert any('Source: Simulation.' in item.value for item in app.caption)
    app.selectbox(key='action_distribution_cause').select('Not recorded').run(timeout=25)
    assert not app.exception
    assert any('do not establish bias' in item.value for item in app.info)



def test_only_latest_active_human_approved_checkout_is_offered(review_ui):
    with review_ui() as db:
        db.add(Payment(payment_id='pay_checkout_ui',amount=499,status='failed'))
        db.add(RecoveryReservation(payment_id='pay_checkout_ui',owner='waiting',state='awaiting_outcome'))
        db.add_all([
            AuditLog(payment_id='pay_checkout_ui',event_type='executed',
                     timestamp=datetime.utcnow()-timedelta(minutes=1),
                     payload_json=json.dumps({'type':'order','order_id':'order_older'})),
            AuditLog(payment_id='pay_checkout_ui',event_type='human_approved_executed',
                     payload_json=json.dumps({'type':'payment_link','payment_link_id':'plink_current',
                                             'short_url':'https://rzp.io/rzp/testCurrent','excluded_method':'card'})),
        ])
        db.commit()
    app = login(AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard.py')).run(timeout=25))
    text = ' '.join(item.value for item in app.markdown)
    assert 'Open alternate-method checkout' in text and 'https://rzp.io/rzp/testCurrent' in text
    assert 'order_older' not in text
    with review_ui() as db:
        db.get(Payment,'pay_checkout_ui').status = 'recovered'; db.commit()
    app.run(timeout=25)
    assert not app.exception
    assert not any('https://rzp.io/rzp/testCurrent' in item.value for item in app.markdown)



def test_live_case_search_and_status_filters_render_without_touching_provider(review_ui):
    with review_ui() as db:
        db.add_all([Payment(payment_id='pay_searchOne',amount=100,status='failed'),
                    Payment(payment_id='pay_searchTwo',amount=200,status='recovered')])
        db.commit()
    app=login(AppTest.from_file(str(Path(__file__).resolve().parents[1]/'dashboard.py')).run(timeout=25))
    app.text_input(key='live_case_search').set_value('searchTwo').run(timeout=25)
    tab=next(tab for tab in app.tabs if tab.label=='Live Razorpay Cases')
    assert list(tab.dataframe[0].value['Payment ID'])==['pay_searchTwo']
    app.selectbox(key='live_case_status').select('failed').run(timeout=25)
    assert not app.exception
    assert any('No Test Mode cases match' in item.value for item in app.info)



def test_old_link_cancellation_requires_check_then_explicit_cancel(review_ui,monkeypatch):
    with review_ui() as db:
        payment=Payment(payment_id='pay_cleanup_ui',amount=499,status='recovered')
        action=Action(payment_id=payment.payment_id,action_type='payment_link',decision_type='auto')
        payload={'type':'payment_link','payment_link_id':'plink_cleanup'}
        audit=AuditLog(payment_id=payment.payment_id,event_type='executed',payload_json=json.dumps(payload))
        db.add_all([payment,action,audit]);db.flush();record_execution(db,payment,action,audit,payload);db.commit()
    state={'id':'plink_cleanup','status':'created','amount':49900,'amount_paid':0,'currency':'INR'}
    fetch=Mock(side_effect=lambda _:state.copy())
    def close(_):state['status']='cancelled';return state.copy()
    cancel=Mock(side_effect=close)
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.fetch',fetch)
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.cancel',cancel)
    source="from app.ui.operator_login import require_dashboard_operator\noperator=require_dashboard_operator()\nfrom app.db.session import SessionLocal\nfrom app.ui.checkout_maintenance import render_checkout_maintenance\nwith SessionLocal() as db:render_checkout_maintenance(db,'pay_cleanup_ui',operator)\n"
    app=login(AppTest.from_string(source).run(timeout=25))
    fetch.assert_not_called();cancel.assert_not_called()
    assert app.button(key='cleanup_cancel_pay_cleanup_ui').disabled
    app.button(key='cleanup_check_pay_cleanup_ui').click().run(timeout=25)
    assert not app.exception and not app.button(key='cleanup_cancel_pay_cleanup_ui').disabled
    cancel.assert_not_called()
    app.button(key='cleanup_cancel_pay_cleanup_ui').click().run(timeout=25)
    assert not app.exception and cancel.call_count==1 and fetch.call_count==2
    assert app.button(key='cleanup_cancel_pay_cleanup_ui').disabled


def test_dashboard_operator_can_record_stop_without_provider_request(review_ui,monkeypatch):
    with review_ui() as db:
        db.add(Payment(payment_id='pay_stop_ui',amount=499,status='failed'));db.commit()
    create=Mock(side_effect=AssertionError('UI stop must not call provider'))
    monkeypatch.setattr('app.services.execution.create_payment_link',create)
    app=login(AppTest.from_file(str(Path(__file__).resolve().parents[1]/'dashboard.py')).run(timeout=25))
    app.selectbox(key='stop_followup_reason').select('customer_opt_out')
    app.button(key='stop_followup_submit').click().run(timeout=25)
    assert not app.exception
    assert any('Further recovery stopped' in item.value for item in app.info)
    with review_ui() as db:
        p=db.get(Payment,'pay_stop_ui')
        assert p.recovery_stop_reason=='customer_opt_out' and p.status=='closed_unrecovered'
    create.assert_not_called()


def test_authenticated_dashboard_loads_test_checkout_without_second_login(review_ui,monkeypatch):
    fetch=Mock(return_value={'id':'order_TestPreview','amount':49900,'currency':'INR','status':'created',
                             'amount_paid':0,'amount_due':49900,'attempts':0})
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',fetch)
    app=login(AppTest.from_file(str(Path(__file__).resolve().parents[1]/'dashboard.py')).run(timeout=25))
    fetch.assert_not_called()
    app.text_input(key='operator_checkout_order').set_value('order_TestPreview')
    app.button(key='operator_checkout_load').click().run(timeout=25)
    assert not app.exception
    fetch.assert_called_once_with('order_TestPreview')
    assert len(app.get('iframe'))==1
    src=app.get('iframe')[0].proto.srcdoc
    assert 'order_TestPreview' in src and 'Start Test Mode payment' in src
    assert settings.operator_password_hash.get_secret_value() not in src


def test_operator_can_return_verified_failed_execution_to_review_without_new_checkout(review_ui,monkeypatch):
    add_case(review_ui)
    monkeypatch.setattr('app.services.reconciliation.client.payment_link.fetch',lambda _: {
        'id':'plink_ui','status':'cancelled','amount':49900,'amount_paid':0,'currency':'INR'})
    create=Mock(side_effect=AssertionError('No new provider creation allowed'))
    monkeypatch.setattr('app.services.execution.create_payment_link',create)
    app=login(AppTest.from_string(REVIEW_APP).run())
    app.button(key='reconciliation_check').click().run(timeout=20)
    assert not app.exception
    assert not app.button(key='reconciliation_failed_review').disabled
    app.button(key='reconciliation_failed_review').click().run(timeout=20)
    assert not app.exception
    with review_ui() as db:
        assert db.get(RecoveryReservation,'pay_ui').state=='pending_review'
        assert db.query(Action).filter_by(payment_id='pay_ui',review_status='pending').one().action_type=='manual_assessment'
    create.assert_not_called()



def test_approved_history_shows_executed_override_and_its_own_audit(review_ui):
    with review_ui() as db:
        payment = Payment(payment_id='pay_history', amount=499, status='failed')
        db.add(payment)
        now = datetime.utcnow()
        db.add(Action(payment_id=payment.payment_id, action_type='manual_assessment',
                      decision_type='human_review', review_status='actioned', chosen_at=now))
        for i, action_type in enumerate(['retry', 'alt_method']):
            payload = ({'type': 'order', 'order_id': 'order_history'} if i == 0 else
                       {'type': 'payment_link', 'payment_link_id': 'plink_history'})
            action = Action(payment_id=payment.payment_id, action_type=action_type,
                            decision_type='auto', chosen_at=now + timedelta(seconds=i),
                            reason='human-approved action (original ML recommendation: manual_assessment)')
            audit = AuditLog(payment_id=payment.payment_id, event_type='human_approved_executed',
                             timestamp=now + timedelta(seconds=i), payload_json=json.dumps(payload))
            db.add_all([action, audit]); db.flush()
            record_execution(db, payment, action, audit, payload)
        # A legacy executed action has no exact binding. It must not borrow the latest audit.
        db.add(Action(payment_id=payment.payment_id, action_type='payment_link', decision_type='auto',
                      chosen_at=now + timedelta(seconds=2), reason='human-approved action (legacy)'))
        db.commit()
    app = login(AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard.py')).run(timeout=25))
    assert not app.exception
    tab = next(tab for tab in app.tabs if tab.label == 'Human Review')
    labels = [item.value for item in tab.markdown if 'human-approved:' in item.value]
    assert labels == [
        '**pay_history** — human-approved: **payment_link**',
        '**pay_history** — human-approved: **alt_method**',
        '**pay_history** — human-approved: **retry**',
    ]
    assert [json.loads(item.value) for item in tab.code] == [
        {'type': 'payment_link', 'payment_link_id': 'plink_history'},
        {'type': 'order', 'order_id': 'order_history'},
    ]
    assert any('Exact execution audit is unavailable' in item.value for item in tab.caption)
    assert any(item.value == 'Recent approved executions' for item in tab.subheader)
    assert not any('this session' in item.value for item in tab.caption)
