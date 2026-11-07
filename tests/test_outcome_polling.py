import json
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Payment,Action,AuditLog,RecoveryReservation,Outcome
from app.services.execution_records import record_execution
from app.services.outcome_polling import poll_pending_outcomes


@pytest.fixture
def polling(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'poll.db').as_posix()}")
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    with factory() as db:
        payment=Payment(payment_id='pay_poll',amount=499,status='failed',razorpay_state='failed')
        action=Action(payment_id='pay_poll',action_type='payment_link',decision_type='auto')
        audit=AuditLog(payment_id='pay_poll',event_type='executed',payload_json=json.dumps(
            {'type':'payment_link','payment_link_id':'plink_poll'}))
        db.add_all([payment,action,audit]);db.flush()
        record_execution(db,payment,action,audit,json.loads(audit.payload_json))
        db.add(RecoveryReservation(payment_id='pay_poll',owner='waiting',state='awaiting_outcome',
                                  updated_at=datetime.utcnow()-timedelta(minutes=5)))
        db.commit()
    yield factory
    engine.dispose()


def link(status='created'):
    return {'id':'plink_poll','amount':49900,'currency':'INR','amount_paid':49900 if status=='paid' else 0,'status':status}


@pytest.mark.parametrize('state',['processing','needs_reconciliation','pending_review'])
def test_polling_never_takes_over_nonwaiting_claims(polling,monkeypatch,state):
    with polling() as db:db.get(RecoveryReservation,'pay_poll').state=state;db.commit()
    fetch=Mock(side_effect=AssertionError('Blocked claims must not contact provider'))
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch',fetch)
    assert poll_pending_outcomes(session_factory=polling)['selected']==0
    fetch.assert_not_called()


def test_due_paid_link_settles_once_without_new_creation(polling,monkeypatch):
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch',lambda _:link('paid'))
    forbidden=Mock(side_effect=AssertionError('Paid recovery must not create a resource'))
    monkeypatch.setattr('app.services.execution.create_payment_link',forbidden)
    assert poll_pending_outcomes(session_factory=polling)['recovered']==1
    assert poll_pending_outcomes(session_factory=polling)['selected']==0
    with polling() as db:
        assert db.get(Payment,'pay_poll').status=='recovered'
        assert db.query(Outcome).count()==1 and db.get(RecoveryReservation,'pay_poll') is None
    forbidden.assert_not_called()


def test_pending_is_throttled_and_does_not_generate_another_action(polling,monkeypatch):
    fetch=Mock(return_value=link());monkeypatch.setattr('app.services.execution.client.payment_link.fetch',fetch)
    assert poll_pending_outcomes(session_factory=polling)['pending']==1
    assert poll_pending_outcomes(session_factory=polling)['selected']==0
    assert fetch.call_count==1
    with polling() as db:assert db.query(Action).count()==1 and db.query(Outcome).count()==0


def test_provider_error_remains_blocked_and_does_not_leak_details(polling,monkeypatch):
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch',Mock(side_effect=TimeoutError('PRIVATE')))
    result=poll_pending_outcomes(session_factory=polling)
    assert result['errors']==1 and 'PRIVATE' not in json.dumps(result)
    with polling() as db:assert db.get(RecoveryReservation,'pay_poll').state=='needs_reconciliation'


def test_other_poller_cannot_enter_an_active_provider_read(polling,monkeypatch):
    started,release=Event(),Event()
    def fetch(_):
        started.set();assert release.wait(5);return link()
    provider=Mock(side_effect=fetch)
    monkeypatch.setattr('app.services.execution.client.payment_link.fetch',provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(poll_pending_outcomes,session_factory=polling)
        assert started.wait(5)
        second=pool.submit(poll_pending_outcomes,session_factory=polling)
        assert second.result(timeout=5)['selected']==0
        release.set();assert first.result(timeout=5)['pending']==1
    assert provider.call_count==1


def test_provider_session_sets_bounded_timeouts_without_network(monkeypatch):
    from app.services.razorpay_client import BoundedProviderSession
    request=Mock(return_value='fixture')
    monkeypatch.setattr('requests.Session.request',request)
    assert BoundedProviderSession().request('GET','https://example.invalid')=='fixture'
    assert request.call_args.kwargs['timeout']==(5,20)



def test_followup_worker_refuses_live_credentials(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'razorpay_key_id','rzp_live_not_authorized')
    with pytest.raises(ValueError,match='Test Mode only'):
        poll_pending_outcomes()
