import hashlib
import hmac
import json
from datetime import datetime,timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.session import Base
from app.models.models import (Payment,Action,AuditLog,Outcome,OriginalOrderRecovery,
                               RecoveryReservation,RecoveryExecution)
from app.services.execution import execute_action,human_review_action,observe_outcome
from app.services.original_orders import (bind_original_order,read_original_order,
    OriginalOrderVerificationError,observe_original_capture)


@pytest.fixture
def scenario(tmp_path,monkeypatch):
    engine=create_engine(f"sqlite:///{(tmp_path/'original.sqlite').as_posix()}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add(Payment(payment_id='pay_failed',order_id='order_original',amount=499,status='failed',razorpay_state='failed'))
        db.commit()
    state={'order':{'id':'order_original','amount':49900,'currency':'INR','status':'attempted',
                    'amount_paid':0,'amount_due':49900,'attempts':1},
           'payments':[{'id':'pay_failed','order_id':'order_original','amount':49900,'currency':'INR','status':'failed'}]}
    monkeypatch.setattr('app.services.razorpay_client.client.order.fetch',lambda _:state['order'].copy())
    monkeypatch.setattr('app.services.razorpay_client.client.order.payments',lambda _: {'count':len(state['payments']),'items':[p.copy() for p in state['payments']]})
    monkeypatch.setattr('app.services.razorpay_client.client.payment.fetch',lambda pid:next(p.copy() for p in state['payments'] if p['id']==pid))
    monkeypatch.setattr('app.services.execution.decide',lambda *_:{'chosen_action':'payment_link','decision_type':'auto','reason':'fixture'})
    provider=Mock(return_value={'id':'plink_followup'})
    monkeypatch.setattr('app.services.execution.create_payment_link',provider)
    yield factory,state,provider
    engine.dispose()


def paid(state):
    state['order'].update(status='paid',amount_paid=49900,amount_due=0,attempts=2)
    state['payments'].append({'id':'pay_direct','order_id':'order_original','amount':49900,'currency':'INR','status':'captured'})


def test_original_paid_before_processing_does_not_create_recovery_or_uplift(scenario):
    factory,state,provider=scenario;paid(state)
    with factory() as db:
        result=execute_action(db,db.get(Payment,'pay_failed'))
        assert not result['executed'] and result['status']=='paid_original'
        assert db.get(Payment,'pay_failed').status=='paid_original'
        assert db.query(Outcome).count()==0
        assert db.query(RecoveryExecution).count()==0
        assert db.get(RecoveryReservation,'pay_failed') is None
    provider.assert_not_called()


def test_original_paid_during_scoring_is_rechecked_before_creation(scenario,monkeypatch):
    factory,state,provider=scenario
    def decide(*_):
        paid(state)
        return {'chosen_action':'payment_link','decision_type':'auto','reason':'fixture'}
    monkeypatch.setattr('app.services.execution.decide',decide)
    with factory() as db:
        assert execute_action(db,db.get(Payment,'pay_failed'))['status']=='paid_original'
    provider.assert_not_called()


def test_original_paid_blocks_human_approval_and_expires_review(scenario):
    factory,state,provider=scenario;paid(state)
    with factory() as db:
        db.add(Action(payment_id='pay_failed',action_type='payment_link',decision_type='human_review',review_status='pending',
                      review_deadline=datetime.utcnow()+timedelta(hours=1)))
        db.commit()
        result=human_review_action(db,'pay_failed','payment_link')
        assert not result['success'] and result['status']=='paid_original'
        assert db.query(Action).one().review_status=='expired'
    provider.assert_not_called()


@pytest.mark.parametrize('condition',['authorized','partial','amount','currency','id','refund','missing_history','inconsistent'])
def test_unsafe_original_order_prevents_new_full_collection(scenario,condition):
    factory,state,provider=scenario
    if condition=='authorized':state['payments'][0]['status']='authorized'
    if condition=='partial':state['order'].update(amount_paid=100,amount_due=49800)
    if condition=='amount':state['order']['amount']=100
    if condition=='currency':state['order']['currency']='USD'
    if condition=='id':state['order']['id']='order_other'
    if condition=='refund':state['payments'][0]['refund_status']='processed'
    if condition=='missing_history':state['payments']=[]
    if condition=='inconsistent':state['order']['status']='paid'
    with factory() as db:
        result=execute_action(db,db.get(Payment,'pay_failed'))
        assert not result['executed'] and result['status']=='needs_reconciliation'
        assert db.get(RecoveryReservation,'pay_failed').state=='needs_reconciliation'
    provider.assert_not_called()


def test_provider_error_does_not_leak_secret_or_create_checkout(scenario,monkeypatch):
    factory,state,provider=scenario
    monkeypatch.setattr('app.services.razorpay_client.client.order.fetch',Mock(side_effect=TimeoutError('PRIVATE_TOKEN')))
    with factory() as db:
        result=execute_action(db,db.get(Payment,'pay_failed'))
        assert result['status']=='needs_reconciliation' and 'PRIVATE' not in str(result)
    provider.assert_not_called()


def test_signed_original_capture_stops_case_and_duplicate_delivery_is_safe(scenario,monkeypatch):
    from app.main import app
    factory,state,provider=scenario
    with factory() as db:
        result=execute_action(db,db.get(Payment,'pay_failed'))
        assert result['executed']
    paid(state)
    monkeypatch.setattr('app.api.webhooks.SessionLocal',factory)
    body=json.dumps({'event':'payment.captured','payload':{'payment':{'entity':{'id':'pay_direct','order_id':'order_original','amount':1}}}}).encode()
    headers={'X-Razorpay-Signature':hmac.new(settings.razorpay_webhook_secret.encode(),body,hashlib.sha256).hexdigest(),
             'X-Razorpay-Event-Id':'evt_direct'}
    with TestClient(app) as transport:
        assert transport.post('/webhooks/razorpay',content=body,headers=headers).json()['status']=='paid_original'
        assert transport.post('/webhooks/razorpay',content=body,headers=headers).json()['status']=='already_processed'
    with factory() as db:
        assert db.get(Payment,'pay_failed').status=='paid_original'
        assert db.query(Outcome).count()==0
        assert db.query(AuditLog).filter_by(event_type='paid_original').count()==1
        assert db.get(RecoveryReservation,'pay_failed') is None
        assert not execute_action(db,db.get(Payment,'pay_failed'))['executed']
    assert provider.call_count==1


def test_busy_original_case_keeps_claim_and_persists_paid_stop_flag(scenario):
    from app.services.reservations import RecoveryInProgress
    factory,state,_=scenario;paid(state)
    with factory() as db:
        bind_original_order(db,db.get(Payment,'pay_failed'))
        db.add(RecoveryReservation(payment_id='pay_failed',owner='another-request',state='processing'));db.commit()
        with pytest.raises(RecoveryInProgress):observe_original_capture(db,'order_original','pay_direct')
        assert db.get(RecoveryReservation,'pay_failed').owner=='another-request'
        assert db.get(OriginalOrderRecovery,'order_original').state=='paid_original'


def test_late_recovery_capture_after_original_success_is_reconciliation_not_uplift(scenario,monkeypatch):
    factory,state,provider=scenario
    with factory() as db:
        assert execute_action(db,db.get(Payment,'pay_failed'))['executed']
        paid(state)
        assert observe_original_capture(db,'order_original','pay_direct')['status']=='paid_original'
        monkeypatch.setattr('app.services.execution.client.payment_link.fetch',lambda _: {
            'id':'plink_followup','status':'paid','amount':49900,'amount_paid':49900,'currency':'INR'})
        assert observe_outcome(db,db.get(Payment,'pay_failed'),expected_payment_link_id='plink_followup')['status']=='needs_reconciliation'
        assert db.get(Payment,'pay_failed').status=='needs_reconciliation'
        assert db.query(Outcome).one().observed_result=='duplicate_payment'
        assert db.get(RecoveryReservation,'pay_failed').state=='needs_reconciliation'
    assert provider.call_count==1


def test_paid_original_allows_reviewed_unpaid_link_cleanup(scenario,monkeypatch):
    from app.services.checkout_maintenance import check_old_link
    factory,state,_=scenario
    with factory() as db:
        execute_action(db,db.get(Payment,'pay_failed'))
        paid(state)
        observe_original_capture(db,'order_original','pay_direct')
        monkeypatch.setattr('app.services.execution.client.payment_link.fetch',lambda _: {
            'id':'plink_followup','status':'created','amount':49900,'amount_paid':0,'currency':'INR'})
        execution=db.query(RecoveryExecution).one()
        assert check_old_link(db,'pay_failed',execution.id)['can_cancel']


def test_original_capture_after_verified_recovery_removes_case_from_uplift(scenario,monkeypatch):
    factory,state,_=scenario
    with factory() as db:
        execute_action(db,db.get(Payment,'pay_failed'))
        monkeypatch.setattr('app.services.execution.client.payment_link.fetch',lambda _: {
            'id':'plink_followup','status':'paid','amount':49900,'amount_paid':49900,'currency':'INR'})
        assert observe_outcome(db,db.get(Payment,'pay_failed'))['status']=='recovered'
        paid(state)
        assert observe_original_capture(db,'order_original','pay_direct')['status']=='needs_reconciliation'
        assert db.get(Payment,'pay_failed').status=='needs_reconciliation'
        assert db.get(RecoveryReservation,'pay_failed').state=='needs_reconciliation'


def test_original_stop_flag_blocks_private_retry_checkout(scenario,monkeypatch):
    from app.main import app
    from app.api.auth import require_operator
    from app.services.execution_records import record_execution
    factory,_,_=scenario
    with factory() as db:
        payment=db.get(Payment,'pay_failed')
        scope=bind_original_order(db,payment);scope.state='paid_original'
        action=Action(payment_id='pay_failed',action_type='retry',decision_type='auto')
        audit=AuditLog(payment_id='pay_failed',event_type='executed',payload_json=json.dumps({'type':'order','order_id':'order_Retry'}))
        db.add_all([action,audit]);db.flush()
        record_execution(db,payment,action,audit,json.loads(audit.payload_json))
        db.add(RecoveryReservation(payment_id='pay_failed',state='awaiting_outcome',owner='waiting'));db.commit()
    monkeypatch.setattr('app.main.SessionLocal',factory)
    monkeypatch.setattr('app.services.razorpay_client.client.order.fetch',lambda _: {
        'id':'order_Retry','amount':49900,'currency':'INR','notes':{'recoverai_intent_id':'known'}})
    app.dependency_overrides[require_operator]=lambda:'operator'
    try:
        with TestClient(app) as transport:
            assert transport.get('/checkout-config?order_id=order_Retry').status_code==409
    finally:
        app.dependency_overrides.clear()


def test_late_capture_still_observed_after_operator_stop(scenario,monkeypatch):
    from app.services.recovery_stops import stop_followup
    factory,state,provider=scenario
    with factory() as db:
        assert execute_action(db,db.get(Payment,'pay_failed'))['executed']
        assert stop_followup(db,'pay_failed','operator','customer_opt_out')['status']=='stopped'
        monkeypatch.setattr('app.services.execution.client.payment_link.fetch',lambda _: {
            'id':'plink_followup','status':'paid','amount':49900,'amount_paid':49900,'currency':'INR'})
        assert observe_outcome(db,db.get(Payment,'pay_failed'),expected_payment_link_id='plink_followup')['status']=='recovered'
        assert db.get(Payment,'pay_failed').recovery_stop_reason=='customer_opt_out'
        assert not execute_action(db,db.get(Payment,'pay_failed'))['executed']
    assert provider.call_count==1
