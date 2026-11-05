import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import (Action, AuditLog, Payment, Outcome, RecoveryReservation,
                               RecoveryIntent, RecoveryExecution, ExecutionOutcome)
from app.services.execution_records import record_execution
from app.services.reconciliation import (check_reconciliation_status, reconcile_verified_success,
                                         list_stuck_cases, ReconciliationError)


@pytest.fixture
def reconciliation(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'review.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    forbidden = Mock(side_effect=AssertionError('Reconciliation must never create external resources'))
    monkeypatch.setattr('app.services.execution.create_test_order', forbidden)
    monkeypatch.setattr('app.services.execution.create_payment_link', forbidden)
    monkeypatch.setattr('app.services.reconciliation.client.order.create', forbidden)
    monkeypatch.setattr('app.services.reconciliation.client.payment_link.create', forbidden)
    yield factory, forbidden
    forbidden.assert_not_called()
    engine.dispose()


def seed(factory, kind='order', state='needs_reconciliation', intent=False, known_id=True, existing_action=False):
    with factory() as db:
        payment = Payment(payment_id='pay_review', amount=499, status='failed')
        db.add(payment)
        if state:
            db.add(RecoveryReservation(payment_id=payment.payment_id, owner='old', state=state))
        provider_id = 'order_review' if kind == 'order' else 'plink_review'
        action = Action(payment_id=payment.payment_id, action_type='retry' if kind == 'order' else 'payment_link',
                        decision_type='auto', chosen_at=datetime.utcnow() - timedelta(minutes=1))
        if intent:
            db.add(RecoveryIntent(id='review-intent', payment_id=payment.payment_id,
                action_type=action.action_type, provider_type=kind, provider_id=provider_id if known_id else None,
                created_at=datetime.utcnow() - timedelta(minutes=2)))
            if existing_action:
                db.add(action)
            key = 'intent:review-intent'
        else:
            payload = {'type': kind, 'order_id' if kind == 'order' else 'payment_link_id': provider_id}
            audit = AuditLog(payment_id=payment.payment_id, event_type='executed', payload_json=json.dumps(payload))
            db.add_all([action, audit]); db.flush()
            execution = record_execution(db, payment, action, audit, payload)
            key = f'execution:{execution.id}'
        db.commit()
        return key, provider_id


def provider(monkeypatch, kind='order', result='success', **updates):
    resource = {'id': 'order_review' if kind == 'order' else 'plink_review', 'amount': 49900, 'currency': 'INR',
                'status': ('paid' if result == 'success' else 'expired' if result == 'failed' else 'created'),
                'amount_paid': 49900 if result == 'success' else 0, 'notes': {'recoverai_intent_id': 'review-intent'}}
    resource.update(updates)
    fetch = Mock(return_value=resource)
    if kind == 'order':
        monkeypatch.setattr('app.services.reconciliation.client.order.fetch', fetch)
        monkeypatch.setattr('app.services.reconciliation.client.order.payments', lambda _: {'items': [{
            'id': 'pay_capture', 'order_id': 'order_review', 'status': 'captured' if result == 'success' else 'failed',
            'amount': 49900, 'currency': 'INR'}] if result != 'pending' else []})
    else:
        monkeypatch.setattr('app.services.reconciliation.client.payment_link.fetch', fetch)
    return fetch, resource


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
def test_preview_has_no_local_writes_and_settlement_is_idempotent(reconciliation, monkeypatch, kind):
    factory, _ = reconciliation
    key, _ = seed(factory, kind)
    provider(monkeypatch, kind)
    with factory() as db:
        assert check_reconciliation_status(db, 'pay_review', key)['result'] == 'success'
        assert db.query(Outcome).count() == 0
        assert db.get(Payment, 'pay_review').status == 'failed'
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'recovered'
        assert db.get(RecoveryReservation, 'pay_review') is None
        assert db.query(Outcome).count() == db.query(ExecutionOutcome).count() == 1
        audit = db.query(AuditLog).filter_by(event_type='reconciliation_settled').one()
        assert json.loads(audit.payload_json)['operator'] == 'operator'
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'blocked'
        assert db.query(Outcome).count() == 1


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
@pytest.mark.parametrize('result', ['failed', 'pending'])
def test_non_success_stays_blocked_without_outcome_or_followup(reconciliation, monkeypatch, kind, result):
    factory, _ = reconciliation
    key, _ = seed(factory, kind)
    provider(monkeypatch, kind, result)
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'not_settled'
        assert db.get(Payment, 'pay_review').status == 'failed'
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'
        assert db.query(Outcome).count() == 0
        assert db.query(Action).count() == 1


@pytest.mark.parametrize('state', ['processing', 'awaiting_outcome', 'pending_review', None])
def test_active_or_absent_claim_cannot_be_taken_over(reconciliation, monkeypatch, state):
    factory, _ = reconciliation
    key, _ = seed(factory, state=state)
    fetch, _ = provider(monkeypatch)
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'blocked'
        claim = db.get(RecoveryReservation, 'pay_review')
        assert (claim.state if claim else None) == state
        assert db.query(Outcome).count() == 0
    fetch.assert_not_called()


@pytest.mark.parametrize('field,value', [('amount', 1), ('currency', 'USD'), ('id', 'order_other')])
def test_mismatched_evidence_does_not_settle(reconciliation, monkeypatch, field, value):
    factory, _ = reconciliation
    key, _ = seed(factory)
    provider(monkeypatch, **{field: value})
    with factory() as db:
        with pytest.raises(ReconciliationError):
            check_reconciliation_status(db, 'pay_review', key)
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'not_settled'
        assert db.query(Outcome).count() == 0
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'


def test_status_is_freshly_verified_after_preview(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, _ = seed(factory, 'payment_link')
    _, resource = provider(monkeypatch, 'payment_link')
    with factory() as db:
        assert check_reconciliation_status(db, 'pay_review', key)['result'] == 'success'
        resource['status'] = 'created'
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'not_settled'
        assert db.query(Outcome).count() == 0


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
@pytest.mark.parametrize('existing_action', [False, True])
def test_lost_response_intent_can_bind_verified_existing_resource_without_creating_one(reconciliation, monkeypatch, kind, existing_action):
    factory, _ = reconciliation
    key, resource_id = seed(factory, kind, intent=True, known_id=False, existing_action=existing_action)
    provider(monkeypatch, kind)
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator', resource_id)['status'] == 'recovered'
        intent = db.get(RecoveryIntent, 'review-intent')
        assert intent.provider_id == resource_id and intent.state == 'bound'
        assert db.query(Action).count() == db.query(RecoveryExecution).count() == db.query(Outcome).count() == 1


def test_wrong_intent_notes_or_foreign_case_cannot_be_settled(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, resource_id = seed(factory, intent=True, known_id=False)
    provider(monkeypatch, notes={'recoverai_intent_id': 'other-intent'})
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator', resource_id)['status'] == 'not_settled'
        assert db.query(RecoveryExecution).count() == db.query(Outcome).count() == 0
        db.add(Payment(payment_id='pay_foreign', amount=499, status='failed'))
        db.commit()
        with pytest.raises(ReconciliationError):
            check_reconciliation_status(db, 'pay_foreign', key, resource_id)


def test_provider_error_is_sanitized_and_block_is_retained(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, _ = seed(factory)
    monkeypatch.setattr('app.services.reconciliation.client.order.fetch', Mock(side_effect=TimeoutError('private_secret')))
    with factory() as db:
        result = reconcile_verified_success(db, 'pay_review', key, 'operator')
        assert result['status'] == 'not_settled' and 'private_secret' not in json.dumps(result)
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'
        assert db.query(Outcome).count() == 0


def test_second_outcome_check_cannot_start_followup_when_status_changes(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, _ = seed(factory)
    provider(monkeypatch)
    monkeypatch.setattr('app.services.execution._check_real_outcome', lambda _: 'failed')
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator')['status'] == 'not_settled'
        assert db.query(Outcome).count() == 0
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'


def test_competing_reconcilers_settle_once(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, _ = seed(factory)
    _, resource = provider(monkeypatch)
    started, release = Event(), Event()
    def fetch(_):
        started.set(); assert release.wait(timeout=10)
        return resource
    monkeypatch.setattr('app.services.reconciliation.client.order.fetch', fetch)
    def settle():
        with factory() as db:
            return reconcile_verified_success(db, 'pay_review', key, 'operator')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(settle)
        try:
            assert started.wait(timeout=10)
            assert settle()['status'] == 'blocked'
        finally:
            release.set()
        assert future.result(timeout=10)['status'] == 'recovered'
    with factory() as db:
        assert db.query(Outcome).count() == 1


def test_empty_operator_is_rejected_before_claim_or_provider_access(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, _ = seed(factory)
    fetch, _ = provider(monkeypatch)
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, '')['status'] == 'blocked'
        assert db.get(RecoveryReservation, 'pay_review').owner == 'old'
        assert list_stuck_cases(db)[0]['payment_id'] == 'pay_review'
    fetch.assert_not_called()


def test_unsettled_intent_binding_is_rolled_back(reconciliation, monkeypatch):
    factory, _ = reconciliation
    key, provider_id = seed(factory, intent=True, known_id=False)
    provider(monkeypatch)
    monkeypatch.setattr('app.services.execution._check_real_outcome', lambda _: 'pending')
    with factory() as db:
        assert reconcile_verified_success(db, 'pay_review', key, 'operator', provider_id)['status'] == 'not_settled'
        assert db.query(Action).count() == db.query(RecoveryExecution).count() == db.query(Outcome).count() == 0
        assert db.get(RecoveryIntent, 'review-intent').execution_id is None
        assert db.get(RecoveryReservation, 'pay_review').state == 'needs_reconciliation'
