from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.models.models import Payment,Action,AuditLog,RecoveryIntent,RecoveryReservation,Outcome
from app.services.execution_records import record_execution
from app.services.reconciliation import return_verified_failure_to_review


@pytest.fixture
def case(tmp_path,monkeypatch):
    engine=create_engine(f"sqlite:///{(tmp_path/'review.sqlite').as_posix()}")
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    with factory() as db:
        payment=Payment(payment_id='pay_review',amount=499,status='failed',razorpay_state='failed')
        action=Action(payment_id='pay_review',action_type='payment_link',decision_type='auto')
        audit=AuditLog(payment_id='pay_review',event_type='executed',payload_json=json.dumps({'type':'payment_link','payment_link_id':'plink_known'}))
        db.add_all([payment,action,audit]);db.flush();execution=record_execution(db,payment,action,audit,json.loads(audit.payload_json))
        key='execution:'+str(execution.id)
        db.add(RecoveryReservation(payment_id='pay_review',owner='old',state='needs_reconciliation'));db.commit()
    resource={'id':'plink_known','status':'cancelled','amount':49900,'amount_paid':0,'currency':'INR'}
    monkeypatch.setattr('app.services.reconciliation.client.payment_link.fetch',lambda _:resource.copy())
    create=Mock(side_effect=AssertionError('Failure review must not create provider resources or invoke ML'))
    monkeypatch.setattr('app.services.execution.create_payment_link',create)
    monkeypatch.setattr('app.services.execution.create_test_order',create)
    monkeypatch.setattr('app.services.execution.decide',create)
    yield factory,key,resource,create
    engine.dispose()


def test_verified_failure_returns_to_review_without_new_external_action(case):
    factory,key,_,create=case
    with factory() as db:
        result=return_verified_failure_to_review(db,'pay_review',key,'operator')
        assert result['status']=='pending_review'
        assert db.get(RecoveryReservation,'pay_review').state=='pending_review'
        assert db.query(Outcome).one().observed_result=='failed'
        review=db.query(Action).filter_by(review_status='pending').one()
        assert review.action_type=='manual_assessment'
        assert db.query(AuditLog).filter_by(event_type='failed_execution_reviewed').one()
        assert return_verified_failure_to_review(db,'pay_review',key,'operator')['status']=='blocked'
        assert db.query(Outcome).count()==1
    create.assert_not_called()


@pytest.mark.parametrize('blocker',['processing','stopped','intent','pending','paid','partial','mismatch','actor'])
def test_uncertain_or_active_cases_stay_blocked(case,blocker):
    factory,key,resource,create=case
    with factory() as db:
        if blocker=='processing':db.get(RecoveryReservation,'pay_review').state='processing'
        if blocker=='stopped':db.get(Payment,'pay_review').recovery_stop_reason='customer_opt_out'
        if blocker=='intent':db.add(RecoveryIntent(id='unknown',payment_id='pay_review',action_type='retry',provider_type='order'))
        db.commit()
        if blocker=='pending':resource['status']='created'
        if blocker=='paid':resource.update(status='paid',amount_paid=49900)
        if blocker=='partial':resource['amount_paid']=100
        if blocker=='mismatch':resource['amount']=100
        result=return_verified_failure_to_review(db,'pay_review',key,'' if blocker=='actor' else 'operator')
        assert result['status']=='blocked'
        assert db.query(Action).filter_by(review_status='pending').count()==0
        assert db.query(Outcome).count()==0
        assert db.get(RecoveryReservation,'pay_review').state==('processing' if blocker=='processing' else 'needs_reconciliation')
    create.assert_not_called()


def test_concurrent_operator_checks_create_one_review(case):
    factory,key,_,create=case;barrier=Barrier(2)
    def resume(_):
        with factory() as db:
            barrier.wait(timeout=10)
            return return_verified_failure_to_review(db,'pay_review',key,'operator')['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(resume,range(2)))==['blocked','pending_review']
    with factory() as db:
        assert db.query(Action).filter_by(review_status='pending').count()==1
    create.assert_not_called()
