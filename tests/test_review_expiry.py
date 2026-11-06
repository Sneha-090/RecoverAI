from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import (Payment, Action, AuditLog, RecoveryReservation, ReviewStatus, Outcome)
from app.services.escalation import expire_overdue_reviews
from app.services.execution import human_review_action, execute_action, observe_outcome


@pytest.fixture
def expiry_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'expiry.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def seed(factory, state='pending_review', payment_status='failed', deadline=None):
    deadline = deadline or datetime.utcnow() - timedelta(hours=1)
    with factory() as db:
        db.add(Payment(payment_id='pay_expiry', amount=499, status=payment_status))
        action = Action(payment_id='pay_expiry', action_type='payment_link', decision_type='human_review',
                        review_status='pending', review_deadline=deadline)
        db.add(action)
        if state:
            db.add(RecoveryReservation(payment_id='pay_expiry', owner='waiting', state=state))
        db.commit()
        return action.id


@pytest.mark.parametrize('state', ['pending_review', None])
def test_expiry_closes_case_releases_claim_and_is_idempotent(expiry_db, monkeypatch, state):
    action_id = seed(expiry_db, state)
    provider = Mock(side_effect=AssertionError('Expiry cannot contact the provider'))
    monkeypatch.setattr('app.services.execution.create_payment_link', provider)
    with expiry_db() as db:
        assert len(expire_overdue_reviews(db)) == 1
        assert expire_overdue_reviews(db) == []
        assert db.get(Action, action_id).review_status == ReviewStatus.expired
        assert db.get(Payment, 'pay_expiry').status == 'closed_unrecovered'
        assert db.get(RecoveryReservation, 'pay_expiry') is None
        assert db.query(AuditLog).filter_by(event_type='human_review_expired').count() == 1
        assert execute_action(db, db.get(Payment, 'pay_expiry'))['executed'] is False
    provider.assert_not_called()


@pytest.mark.parametrize('state', ['processing', 'needs_reconciliation', 'awaiting_outcome'])
def test_expiry_never_takes_other_operation_phases(expiry_db, state):
    action_id = seed(expiry_db, state)
    with expiry_db() as db:
        assert expire_overdue_reviews(db) == []
        assert db.get(Action, action_id).review_status == ReviewStatus.pending
        assert db.get(RecoveryReservation, 'pay_expiry').state == state
        assert db.query(AuditLog).count() == 0


@pytest.mark.parametrize('offset,expires', [(-1, True), (0, True), (1, False)])
def test_expiry_deadline_boundary(expiry_db, offset, expires):
    now = datetime.utcnow()
    seed(expiry_db, deadline=now + timedelta(seconds=offset))
    with expiry_db() as db:
        assert bool(expire_overdue_reviews(db, now=now)) == expires


def test_expiry_preserves_other_pending_review_and_recovered_status(expiry_db):
    seed(expiry_db, payment_status='recovered')
    with expiry_db() as db:
        db.add(Action(payment_id='pay_expiry', action_type='retry', decision_type='human_review',
                      review_status='pending', review_deadline=datetime.utcnow()+timedelta(hours=1)))
        db.commit()
        assert len(expire_overdue_reviews(db)) == 1
        assert db.get(Payment, 'pay_expiry').status == 'recovered'
        assert db.get(RecoveryReservation, 'pay_expiry').state == 'pending_review'


def test_expiry_failure_rolls_back_case_audit_and_claim_together(expiry_db, monkeypatch):
    action_id = seed(expiry_db)
    with expiry_db() as db:
        monkeypatch.setattr(db, 'commit', Mock(side_effect=RuntimeError('database failure')))
        with pytest.raises(RuntimeError):
            expire_overdue_reviews(db)
    with expiry_db() as db:
        assert db.get(Action, action_id).review_status == ReviewStatus.pending
        assert db.get(Payment, 'pay_expiry').status == 'failed'
        assert db.get(RecoveryReservation, 'pay_expiry').state == 'pending_review'
        assert db.query(AuditLog).count() == 0


def test_approval_after_deadline_uses_same_closure_and_audit(expiry_db, monkeypatch):
    action_id = seed(expiry_db)
    provider = Mock(side_effect=AssertionError('Expired review must not execute'))
    monkeypatch.setattr('app.services.execution.create_payment_link', provider)
    with expiry_db() as db:
        assert human_review_action(db, 'pay_expiry', 'payment_link')['success'] is False
        assert db.get(Payment, 'pay_expiry').status == 'closed_unrecovered'
        assert db.get(Action, action_id).review_status == ReviewStatus.expired
        assert db.get(RecoveryReservation, 'pay_expiry') is None
        assert db.query(AuditLog).filter_by(event_type='human_review_expired').count() == 1
    provider.assert_not_called()


def test_two_expiry_workers_create_one_audit(expiry_db):
    seed(expiry_db)
    def expire():
        with expiry_db() as db:
            return len(expire_overdue_reviews(db))
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _: expire(), range(2)))
    assert sum(counts) == 1
    with expiry_db() as db:
        assert db.query(AuditLog).count() == 1
        assert db.get(RecoveryReservation, 'pay_expiry') is None


def test_approval_in_progress_cannot_be_expired(expiry_db, monkeypatch):
    seed(expiry_db, deadline=datetime.utcnow()+timedelta(hours=1))
    started, release = Event(), Event()
    def create(*args, **kwargs):
        started.set(); assert release.wait(timeout=10)
        return {'id': 'plink_approved'}
    monkeypatch.setattr('app.services.execution.create_payment_link', create)
    def approve():
        with expiry_db() as db:
            return human_review_action(db, 'pay_expiry', 'payment_link')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(approve)
        try:
            assert started.wait(timeout=10)
            with expiry_db() as db:
                assert expire_overdue_reviews(db, now=datetime.utcnow()+timedelta(hours=2)) == []
        finally:
            release.set()
        assert future.result(timeout=10)['success'] is True
    with expiry_db() as db:
        assert db.query(AuditLog).filter_by(event_type='human_review_expired').count() == 0


def test_expiry_wins_before_concurrent_approval_without_provider_call(expiry_db, monkeypatch):
    import app.services.escalation as escalation
    import app.services.execution as execution
    seed(expiry_db)
    started, release, approval_started = Event(), Event(), Event()
    original_expire = escalation.expire_review_under_claim
    original_reserve = execution.reserve_recovery
    def hold(*args, **kwargs):
        result = original_expire(*args, **kwargs)
        started.set(); assert release.wait(timeout=10)
        return result
    def reserve(*args, **kwargs):
        approval_started.set()
        return original_reserve(*args, **kwargs)
    monkeypatch.setattr(escalation, 'expire_review_under_claim', hold)
    monkeypatch.setattr(execution, 'reserve_recovery', reserve)
    provider = Mock(side_effect=AssertionError('Expiry won; no external creation'))
    monkeypatch.setattr(execution, 'create_payment_link', provider)
    def expire():
        with expiry_db() as db:
            return len(expire_overdue_reviews(db))
    def approve():
        with expiry_db() as db:
            return human_review_action(db, 'pay_expiry', 'payment_link')
    with ThreadPoolExecutor(max_workers=2) as pool:
        expiry = pool.submit(expire)
        try:
            assert started.wait(timeout=10)
            approval = pool.submit(approve)
            assert approval_started.wait(timeout=10)
        finally:
            release.set()
        assert expiry.result(timeout=10) == 1
        assert approval.result(timeout=10)['success'] is False
    provider.assert_not_called()


def test_verified_late_capture_can_recover_a_review_expired_case(expiry_db, monkeypatch):
    import json
    from app.services.execution_records import record_execution
    seed(expiry_db)
    with expiry_db() as db:
        action = Action(payment_id='pay_expiry', action_type='retry', decision_type='auto',
                        chosen_at=datetime.utcnow()-timedelta(hours=2))
        payload = {'type': 'order', 'order_id': 'order_late'}
        audit = AuditLog(payment_id='pay_expiry', event_type='executed',
                         timestamp=datetime.utcnow()-timedelta(hours=1), payload_json=json.dumps(payload))
        db.add_all([action, audit]); db.flush()
        record_execution(db, db.get(Payment, 'pay_expiry'), action, audit, payload)
        db.commit()
        assert len(expire_overdue_reviews(db)) == 1
        assert db.get(Payment, 'pay_expiry').status == 'closed_unrecovered'
        monkeypatch.setattr('app.services.execution.client.order.payments', lambda _: {
            'items': [{'status': 'captured', 'amount': 49900, 'currency': 'INR'}]})
        assert observe_outcome(db, db.get(Payment, 'pay_expiry'), expected_order_id='order_late')['status'] == 'recovered'
        assert db.query(Outcome).one().observed_result == 'success'
