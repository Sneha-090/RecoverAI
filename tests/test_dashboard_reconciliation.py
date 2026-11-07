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
