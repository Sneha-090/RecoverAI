import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.session import Base
from app.main import app
from app.models.models import (Payment, Action, AuditLog, Outcome, RecoveryIntent,
                               RecoveryReservation, WebhookInbox, WebhookReceipt)
from app.services.execution_records import record_execution
from app.services.webhook_inbox import remember_verified_event, MAX_REPLAY_ATTEMPTS
from app.services.webhook_replay import replay_batch


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'inbox.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr('app.api.webhooks.SessionLocal', factory)
    yield factory, TestClient(app)
    engine.dispose()


def event_body(kind='order', event='payment.captured'):
    return {'event': event, 'payload': {'payment': {'entity': {
        'id': 'pay_provider', 'order_id': 'order_early' if kind == 'order' else 'order_link',
        'description': '#early' if kind == 'payment_link' else 'Private purchase description',
        'contact': 'private-contact', 'email': 'private@example.test', 'card': {'last4': 'private'},
    }}}}


def deliver(client, payload, event_id='evt_early', valid=True):
    body = json.dumps(payload).encode()
    signature = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post('/webhooks/razorpay', content=body, headers={
        'X-Razorpay-Event-Id': event_id, 'X-Razorpay-Signature': signature if valid else 'invalid'})


def creating_intent(factory, kind):
    with factory() as db:
        db.add(Payment(payment_id='pay_original', amount=499, status='failed'))
        db.add(RecoveryIntent(id='intent_early', payment_id='pay_original',
                              action_type='retry' if kind == 'order' else 'payment_link', provider_type=kind))
        db.add(RecoveryReservation(payment_id='pay_original', owner='creator', state='processing'))
        db.commit()


def bind_execution(factory, kind):
    with factory() as db:
        payment = db.get(Payment, 'pay_original')
        action = Action(payment_id=payment.payment_id, action_type='retry' if kind == 'order' else 'payment_link',
                        decision_type='auto', chosen_at=datetime.utcnow() - timedelta(seconds=1))
        resource_id = ('order_' if kind == 'order' else 'plink_') + 'early'
        payload = {'type': kind, 'order_id' if kind == 'order' else 'payment_link_id': resource_id}
        audit = AuditLog(payment_id=payment.payment_id, event_type='executed', payload_json=json.dumps(payload))
        db.add_all([action, audit])
        db.flush()
        execution = record_execution(db, payment, action, audit, payload)
        intent = db.get(RecoveryIntent, 'intent_early')
        intent.provider_id, intent.execution_id, intent.state = resource_id, execution.id, 'bound'
        db.get(RecoveryReservation, payment.payment_id).state = 'awaiting_outcome'
        db.commit()


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
@pytest.mark.parametrize('event', ['payment.captured', 'payment.failed'])
def test_early_event_replays_after_execution_persists(inbox, monkeypatch, kind, event):
    factory, client = inbox
    creating_intent(factory, kind)
    resource = {'id': ('order_' if kind == 'order' else 'plink_') + 'early',
                'notes': {'recoverai_intent_id': 'intent_early'},
                'status': 'paid' if event == 'payment.captured' else 'created',
                'amount': 49900, 'amount_paid': 49900 if event == 'payment.captured' else 0, 'currency': 'INR'}
    monkeypatch.setattr('app.services.webhook_inbox.client.order.fetch', lambda _: resource)
    monkeypatch.setattr('app.services.webhook_inbox.client.payment_link.fetch', lambda _: resource)
    ingest = Mock(side_effect=AssertionError('Early recovery must not become a separate case'))
    monkeypatch.setattr('app.api.webhooks.fetch_and_store_payment', ingest)
    assert deliver(client, event_body(kind, event)).json()['status'] == 'waiting_for_execution'
    with factory() as db:
        row = db.get(WebhookInbox, 'evt_early')
        assert row.state == 'waiting_for_execution' and row.attempts == 1
        assert db.get(WebhookReceipt, row.event_id).state == row.state
        assert db.query(Payment).count() == 1 and db.query(Outcome).count() == 0
    bind_execution(factory, kind)
    monkeypatch.setattr('app.services.execution.client.order.payments', lambda _: {'items': [{
        'status': 'captured' if event == 'payment.captured' else 'failed', 'amount': 49900, 'currency': 'INR'}]})
    advance = Mock(return_value={'decision_type': 'skip', 'reason': 'Test end', 'executed': False})
    monkeypatch.setattr('app.services.execution._execute_action', advance)
    summary = replay_batch(event_id='evt_early', session_factory=factory)
    assert summary['processed'] == 1 and summary['errors'] == 0
    with factory() as db:
        expected = 'recovered' if event == 'payment.captured' else 'closed_unrecovered' if kind == 'order' else 'failed'
        assert db.get(Payment, 'pay_original').status == expected
        assert db.get(WebhookInbox, 'evt_early').state == 'processed'
        assert db.query(Outcome).count() == (0 if kind == 'payment_link' and event == 'payment.failed' else 1)
    assert replay_batch(event_id='evt_early', session_factory=factory)['selected'] == 0
    assert deliver(client, event_body(kind, event)).json()['status'] == 'already_processed'
    assert advance.call_count == (1 if kind == 'order' and event == 'payment.failed' else 0)
    ingest.assert_not_called()


def test_minimal_storage_and_conflicting_event_id(inbox):
    factory, client = inbox
    payload = event_body()
    assert deliver(client, payload).status_code == 200
    with factory() as db:
        stored = db.get(WebhookInbox, 'evt_early').payload_json
        assert not any(word in stored.lower() for word in ['private', 'contact', 'signature', 'card'])
    payload['payload']['payment']['entity']['id'] = 'pay_different'
    assert deliver(client, payload).status_code == 409
    with factory() as db:
        assert db.get(WebhookInbox, 'evt_early').payload_json == stored


def test_invalid_signature_never_stored(inbox):
    factory, client = inbox
    assert deliver(client, event_body(), valid=False).status_code == 400
    with factory() as db:
        assert db.query(WebhookInbox).count() == db.query(WebhookReceipt).count() == 0


@pytest.mark.parametrize('payload', [[], {'event': 'payment.captured'},
    {'event': 'payment.failed', 'payload': {'payment': {'entity': []}}},
    {'event': 'payment.failed', 'payload': {'payment': {'entity': {'id': {}}}}}])
def test_malformed_verified_payload_never_stored(inbox, payload):
    factory, client = inbox
    assert deliver(client, payload).status_code == 400
    with factory() as db:
        assert db.query(WebhookInbox).count() == 0


def test_backoff_and_explicit_waiting_event_retry(inbox):
    factory, client = inbox
    deliver(client, event_body())
    assert replay_batch(session_factory=factory)['selected'] == 0
    assert replay_batch(event_id='evt_early', session_factory=factory)['waiting'] == 1
    with factory() as db:
        row = db.get(WebhookInbox, 'evt_early')
        assert row.attempts == 2 and row.available_at > datetime.utcnow()


def test_bounded_retries_keep_unmatched_event_for_reconciliation(inbox):
    factory, client = inbox
    deliver(client, event_body())
    with factory() as db:
        db.get(WebhookInbox, 'evt_early').attempts = MAX_REPLAY_ATTEMPTS - 1
        db.commit()
    assert replay_batch(event_id='evt_early', session_factory=factory)['blocked'] == 1
    with factory() as db:
        row = db.get(WebhookInbox, 'evt_early')
        assert row.state == 'needs_reconciliation' and row.payload_json
        assert db.get(WebhookReceipt, row.event_id).state == row.state
    assert replay_batch(event_id='evt_early', session_factory=factory)['selected'] == 0


@pytest.mark.parametrize('state', ['processing', 'needs_reconciliation', 'processed'])
def test_worker_never_forces_claims(inbox, state):
    factory, client = inbox
    with factory() as db:
        remember_verified_event(db, 'evt_blocked', event_body())
        db.add(WebhookReceipt(event_id='evt_blocked', state=state))
        db.commit()
    assert deliver(client, event_body(), 'evt_blocked').status_code == (200 if state == 'processed' else 503)
    assert replay_batch(event_id='evt_blocked', session_factory=factory)['selected'] == 0
    with factory() as db:
        assert db.get(WebhookInbox, 'evt_blocked').state == state


def test_temporary_provider_lookup_failure_waits_safely(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    monkeypatch.setattr('app.services.webhook_inbox.client.order.fetch', Mock(side_effect=TimeoutError('private-provider-error')))
    ingest = Mock(side_effect=AssertionError('Must not ingest possible early recovery'))
    monkeypatch.setattr('app.api.webhooks.fetch_and_store_payment', ingest)
    response = deliver(client, event_body(event='payment.failed'))
    assert response.json()['status'] == 'waiting_for_execution'
    assert 'private-provider-error' not in response.text
    with factory() as db:
        assert db.get(WebhookReceipt, 'evt_early').state == 'waiting_for_execution'
        assert db.query(Payment).count() == 1
    ingest.assert_not_called()


def test_competing_workers_observe_once(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    deliver(client, event_body())
    bind_execution(factory, 'order')
    started, release = Event(), Event()
    def capture(_):
        started.set()
        assert release.wait(timeout=10)
        return {'items': [{'status': 'captured', 'amount': 49900, 'currency': 'INR'}]}
    provider = Mock(side_effect=capture)
    monkeypatch.setattr('app.services.execution.client.order.payments', provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(replay_batch, event_id='evt_early', session_factory=factory)
        try:
            assert started.wait(timeout=10)
            assert replay_batch(event_id='evt_early', session_factory=factory)['processed'] == 0
        finally:
            release.set()
        assert future.result(timeout=10)['processed'] == 1
    assert provider.call_count == 1
    with factory() as db:
        assert db.query(Outcome).count() == 1
        assert db.get(WebhookInbox, 'evt_early').state == 'processed'


def test_unrelated_original_failure_still_processes_during_another_creation(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    monkeypatch.setattr('app.services.webhook_inbox.client.order.fetch', lambda key: {'id': key, 'notes': {}})
    with factory() as db:
        db.add(Payment(payment_id='pay_provider', amount=100, status='failed'))
        db.commit()
    def fetch(db, key):
        return db.get(Payment, key)
    monkeypatch.setattr('app.api.webhooks.fetch_and_store_payment', fetch)
    monkeypatch.setattr('app.api.webhooks.diagnose_and_store', lambda *args: type('Diagnosis', (), {'cause': 'test'})())
    monkeypatch.setattr('app.api.webhooks.execute_action', lambda *args: {
        'chosen_action': None, 'decision_type': 'skip', 'executed': False})
    assert deliver(client, event_body(event='payment.failed')).json()['status'] == 'processed'
    with factory() as db:
        assert db.get(WebhookInbox, 'evt_early').state == 'processed'
        assert db.get(RecoveryIntent, 'intent_early').state == 'creating'


def test_execution_committed_during_lookup_does_not_become_a_new_case(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    def creation_finished(db, entity):
        bind_execution(factory, 'order')
        return None
    monkeypatch.setattr('app.api.webhooks.unpersisted_recovery_intent', creation_finished)
    ingest = Mock(side_effect=AssertionError('Correlation appeared during lookup'))
    monkeypatch.setattr('app.api.webhooks.fetch_and_store_payment', ingest)
    assert deliver(client, event_body(event='payment.failed')).json()['status'] == 'waiting_for_execution'
    ingest.assert_not_called()


def test_due_worker_can_process_waiting_capture_without_explicit_event_id(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    deliver(client, event_body())
    bind_execution(factory, 'order')
    with factory() as db:
        db.get(WebhookInbox, 'evt_early').available_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr('app.services.execution.client.order.payments', lambda _: {'items': [{
        'status': 'captured', 'amount': 49900, 'currency': 'INR'}]})
    assert replay_batch(limit=1, session_factory=factory)['processed'] == 1


def test_worker_failure_blocks_reconciliation_and_does_not_log_private_error(inbox, monkeypatch):
    factory, client = inbox
    creating_intent(factory, 'order')
    deliver(client, event_body())
    bind_execution(factory, 'order')
    monkeypatch.setattr('app.services.execution.client.order.payments', Mock(side_effect=TimeoutError('private-provider-error')))
    summary = replay_batch(event_id='evt_early', session_factory=factory)
    assert summary['errors'] == summary['blocked'] == 1
    assert 'private-provider-error' not in json.dumps(summary)
    with factory() as db:
        assert db.get(WebhookReceipt, 'evt_early').state == 'needs_reconciliation'
        assert db.get(WebhookInbox, 'evt_early').state == 'needs_reconciliation'
    assert replay_batch(event_id='evt_early', session_factory=factory)['selected'] == 0


def test_historically_processed_audit_marks_new_inbox_row_completed(inbox):
    factory, client = inbox
    with factory() as db:
        db.add(Payment(payment_id='pay_original', amount=100, status='recovered'))
        db.add(AuditLog(payment_id='pay_original', event_type='webhook_processed', razorpay_event_id='evt_early'))
        db.commit()
    assert deliver(client, event_body()).json()['status'] == 'already_processed'
    with factory() as db:
        assert db.get(WebhookInbox, 'evt_early').state == 'processed'


def test_replay_cli_list_is_read_only_and_omits_payload(inbox, monkeypatch, capsys):
    from scripts import replay_webhooks
    factory, client = inbox
    deliver(client, event_body())
    monkeypatch.setattr(replay_webhooks, 'SessionLocal', factory)
    process = Mock(side_effect=AssertionError('Listing must not process'))
    monkeypatch.setattr(replay_webhooks, 'replay_batch', process)
    replay_webhooks.main(['--list'])
    rows = json.loads(capsys.readouterr().out)
    assert rows == [{'event_id': 'evt_early', 'state': 'waiting_for_execution', 'attempts': 1}]
    process.assert_not_called()


@pytest.mark.parametrize('arguments', [['--limit', '0'], ['--interval', '0'], ['--watch', '--event-id', 'evt_early']])
def test_replay_cli_rejects_unsafe_or_unbounded_arguments(arguments):
    from scripts.replay_webhooks import main
    with pytest.raises(SystemExit) as caught:
        main(arguments)
    assert caught.value.code == 2


@pytest.mark.parametrize('reference', ['unknown-intent', {'invalid': 'reference'}])
def test_unknown_provider_reference_never_becomes_a_new_case(inbox, monkeypatch, reference):
    factory, client = inbox
    creating_intent(factory, 'order')
    monkeypatch.setattr('app.services.webhook_inbox.client.order.fetch', lambda key: {
        'id': key, 'notes': {'recoverai_intent_id': reference}})
    ingest = Mock(side_effect=AssertionError('Unknown metadata requires reconciliation'))
    monkeypatch.setattr('app.api.webhooks.fetch_and_store_payment', ingest)
    assert deliver(client, event_body(event='payment.failed')).json()['status'] == 'waiting_for_execution'
    ingest.assert_not_called()


def test_invalid_event_type_is_rejected(inbox):
    factory, client = inbox
    assert deliver(client, {'event': []}).status_code == 400
    with factory() as db:
        assert db.query(WebhookInbox).count() == 0
