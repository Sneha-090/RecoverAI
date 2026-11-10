from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.session import Base
from app.models.models import Payment, Action, AuditLog, RecoveryIntent, RecoveryReservation, Outcome
from app.services.execution_records import record_execution
from app.services.reconciliation import resume_unattempted_retry


@pytest.fixture
def case(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'resume.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        payment = Payment(payment_id='pay_resume', order_id='order_original', amount=499,
                          status='failed', razorpay_state='failed')
        action = Action(payment_id=payment.payment_id, action_type='retry', decision_type='auto')
        payload = {'type': 'order', 'order_id': 'order_retry'}
        audit = AuditLog(payment_id=payment.payment_id, event_type='executed', payload_json=json.dumps(payload))
        db.add_all([payment, action, audit]); db.flush()
        execution = record_execution(db, payment, action, audit, payload)
        key = 'execution:' + str(execution.id)
        db.add(RecoveryReservation(payment_id=payment.payment_id, owner='old', state='needs_reconciliation'))
        db.commit()
    resource = {'id': 'order_retry', 'status': 'created', 'amount': 49900, 'currency': 'INR',
                'amount_paid': 0, 'amount_due': 49900, 'attempts': 0}
    history = {'count': 0, 'items': []}
    monkeypatch.setattr('app.services.reconciliation.client.order.fetch', lambda _: resource.copy())
    monkeypatch.setattr('app.services.reconciliation.client.order.payments', lambda _: history.copy())
    monkeypatch.setattr('app.services.original_orders.read_original_order', lambda _: {'status': 'open'})
    create = Mock(side_effect=AssertionError('Review must never create a resource or invoke ML'))
    monkeypatch.setattr('app.services.execution.create_test_order', create)
    monkeypatch.setattr('app.services.execution.create_payment_link', create)
    monkeypatch.setattr('app.services.execution.decide', create)
    yield factory, key, resource, history, create
    engine.dispose()


def test_review_resumes_only_existing_unattempted_order_without_creation(case):
    factory, key, _, _, create = case
    with factory() as db:
        assert resume_unattempted_retry(db, 'pay_resume', key, 'operator')['status'] == 'awaiting_outcome'
        assert db.get(RecoveryReservation, 'pay_resume').state == 'awaiting_outcome'
        assert db.query(Action).count() == 1 and db.query(Outcome).count() == 0
        assert db.query(AuditLog).filter_by(event_type='unattempted_retry_resumed').count() == 1
        assert resume_unattempted_retry(db, 'pay_resume', key, 'operator')['status'] == 'blocked'
    create.assert_not_called()


@pytest.mark.parametrize('blocker', ['processing', 'stopped', 'closed', 'intent', 'outcome', 'actor',
    'paid', 'partial', 'attempted', 'payments', 'mismatch', 'currency', 'due', 'identity', 'original_paid', 'unavailable', 'live'])
def test_unsafe_unattempted_resumption_stays_blocked(case, monkeypatch, blocker):
    factory, key, resource, history, create = case
    with factory() as db:
        if blocker == 'processing': db.get(RecoveryReservation, 'pay_resume').state = 'processing'
        if blocker == 'stopped': db.get(Payment, 'pay_resume').recovery_stop_reason = 'customer_opt_out'
        if blocker == 'closed': db.get(Payment, 'pay_resume').status = 'closed_unrecovered'
        if blocker == 'intent': db.add(RecoveryIntent(id='unknown', payment_id='pay_resume', action_type='retry', provider_type='order'))
        if blocker == 'outcome': db.add(Outcome(payment_id='pay_resume', action_type='retry', observed_result='failed'))
        db.commit()
        if blocker == 'paid': resource.update(status='paid', amount_paid=49900)
        if blocker == 'partial': resource['amount_paid'] = 100
        if blocker == 'attempted': resource.update(status='attempted', attempts=1)
        if blocker == 'payments': history.update(count=1, items=[{'status': 'authorized'}])
        if blocker == 'mismatch': resource['amount'] = 100
        if blocker == 'currency': resource['currency'] = 'USD'
        if blocker == 'due': resource['amount_due'] = 100
        if blocker == 'identity': resource['id'] = 'order_other'
        if blocker == 'original_paid': monkeypatch.setattr('app.services.original_orders.read_original_order', lambda _: {'status': 'paid'})
        if blocker == 'unavailable': monkeypatch.setattr('app.services.reconciliation.client.order.fetch', Mock(side_effect=TimeoutError('PRIVATE')))
        if blocker == 'live': monkeypatch.setattr(settings, 'razorpay_key_id', 'rzp_live_fixture')
        result = resume_unattempted_retry(db, 'pay_resume', key, '' if blocker == 'actor' else 'operator')
        assert result['status'] == 'blocked' and 'PRIVATE' not in result['reason']
        assert db.get(RecoveryReservation, 'pay_resume').state == ('processing' if blocker == 'processing' else 'needs_reconciliation')
        assert db.query(AuditLog).filter_by(event_type='unattempted_retry_resumed').count() == 0
    create.assert_not_called()


def test_competing_reviews_resume_one_existing_order(case):
    factory, key, _, _, create = case
    barrier = Barrier(2)
    def run(_):
        with factory() as db:
            barrier.wait(timeout=10)
            return resume_unattempted_retry(db, 'pay_resume', key, 'operator')['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['awaiting_outcome', 'blocked']
    with factory() as db:
        assert db.query(AuditLog).filter_by(event_type='unattempted_retry_resumed').count() == 1
    create.assert_not_called()



@pytest.mark.parametrize('history_problem', ['missing_original', 'other_action', 'unattributed_action', 'second_execution'])
def test_incomplete_or_multiple_execution_history_never_resumes(case, history_problem):
    factory, key, _, _, create = case
    with factory() as db:
        if history_problem == 'missing_original': db.get(Payment, 'pay_resume').order_id = None
        if history_problem == 'other_action': db.query(Action).one().action_type = 'alt_method'
        if history_problem in {'unattributed_action', 'second_execution'}:
            action = Action(payment_id='pay_resume', action_type='payment_link', decision_type='auto')
            db.add(action); db.flush()
            if history_problem == 'second_execution':
                payload = {'type': 'payment_link', 'payment_link_id': 'plink_other'}
                audit = AuditLog(payment_id='pay_resume', event_type='executed', payload_json=json.dumps(payload))
                db.add(audit); db.flush()
                record_execution(db, db.get(Payment, 'pay_resume'), action, audit, payload)
        db.commit()
        assert resume_unattempted_retry(db, 'pay_resume', key, 'operator')['status'] == 'blocked'
        assert db.get(RecoveryReservation, 'pay_resume').state == 'needs_reconciliation'
    create.assert_not_called()


def test_stop_recorded_during_provider_read_blocks_resumption(case, monkeypatch):
    factory, key, resource, _, create = case
    def stop_during_read(_):
        with factory() as other:
            other.get(Payment, 'pay_resume').recovery_stop_reason = 'fraud_concern'
            other.commit()
        return resource.copy()
    monkeypatch.setattr('app.services.reconciliation.client.order.fetch', stop_during_read)
    with factory() as db:
        assert resume_unattempted_retry(db, 'pay_resume', key, 'operator')['status'] == 'blocked'
        assert db.get(RecoveryReservation, 'pay_resume').state == 'needs_reconciliation'
        assert db.query(AuditLog).filter_by(event_type='unattempted_retry_resumed').count() == 0
    create.assert_not_called()
