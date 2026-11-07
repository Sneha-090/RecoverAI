import json
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.session import Base
from app.models.models import Payment,Action,AuditLog,RecoveryReservation
from app.services.execution_records import record_execution
from app.services.checkout_maintenance import check_old_link,cancel_old_link


@pytest.fixture
def cleanup_db(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'cleanup.db').as_posix()}",connect_args={'check_same_thread':False});Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        payment=Payment(payment_id='pay_old',amount=499,status='recovered')
        action=Action(payment_id='pay_old',action_type='payment_link',decision_type='auto')
        audit=AuditLog(payment_id='pay_old',event_type='executed',payload_json=json.dumps(
            {'type':'payment_link','payment_link_id':'plink_old'}))
        db.add_all([payment,action,audit]);db.flush()
        record_execution(db,payment,action,audit,json.loads(audit.payload_json));db.commit()
        yield db
    engine.dispose()


def resource(status='created',paid=0):
    return {'id':'plink_old','amount':49900,'currency':'INR','status':status,'amount_paid':paid}


@pytest.mark.parametrize('status,paid',[('paid',49900),('partially_paid',100),('cancelled',0),('expired',0)])
def test_paid_partial_and_inactive_links_cannot_be_cancelled(cleanup_db,monkeypatch,status,paid):
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.fetch',lambda _:resource(status,paid))
    cancel=Mock();monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.cancel',cancel)
    assert not check_old_link(cleanup_db,'pay_old',1)['can_cancel']
    assert cancel_old_link(cleanup_db,'pay_old',1,'operator')['status']=='not_needed'
    cancel.assert_not_called()


def test_closed_case_cancellation_checks_identity_and_records_result(cleanup_db,monkeypatch):
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.fetch',lambda _:resource())
    cancel=Mock(return_value=resource('cancelled'))
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.cancel',cancel)
    assert cancel_old_link(cleanup_db,'pay_old',1,'operator')['status']=='cancelled'
    cancel.assert_called_once_with('plink_old')
    assert cleanup_db.get(Payment,'pay_old').status=='recovered'
    assert cleanup_db.get(RecoveryReservation,'pay_old') is None
    assert cleanup_db.query(AuditLog).filter_by(event_type='old_link_cancelled').count()==1


def test_lost_cancellation_response_is_refetched_not_blindly_repeated(cleanup_db,monkeypatch):
    state=resource()
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.fetch',lambda _:state.copy())
    def lost(_):state['status']='cancelled';raise TimeoutError('PRIVATE')
    cancel=Mock(side_effect=lost);monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.cancel',cancel)
    result=cancel_old_link(cleanup_db,'pay_old',1,'operator')
    assert result['status']=='unconfirmed' and 'PRIVATE' not in json.dumps(result)
    assert cancel_old_link(cleanup_db,'pay_old',1,'operator')['status']=='not_needed'
    assert cancel.call_count==1


@pytest.mark.parametrize('blocker',['active','claim','mismatch'])
def test_unsafe_cancellation_is_blocked(cleanup_db,monkeypatch,blocker):
    data=resource()
    if blocker=='active':cleanup_db.get(Payment,'pay_old').status='failed'
    if blocker=='claim':cleanup_db.add(RecoveryReservation(payment_id='pay_old',owner='busy',state='processing'))
    if blocker=='mismatch':data['amount']=1
    cleanup_db.commit()
    monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.fetch',lambda _:data)
    cancel=Mock();monkeypatch.setattr('app.services.checkout_maintenance.client.payment_link.cancel',cancel)
    assert cancel_old_link(cleanup_db,'pay_old',1,'operator')['status'] in {'blocked','unconfirmed'}
    cancel.assert_not_called()


def test_inactive_recovery_order_cannot_reopen_checkout(monkeypatch,cleanup_db):
    from app.main import app
    from app.api.auth import require_operator
    monkeypatch.setattr('app.services.razorpay_client.client.order.fetch',lambda _: {
        'id':'order_closed','amount':49900,'currency':'INR','notes':{'recoverai_intent_id':'existing'}})
    # This recovery order has no active execution/claim and must fail closed.
    from contextlib import nullcontext
    monkeypatch.setattr('app.main.SessionLocal',lambda:nullcontext(cleanup_db))
    app.dependency_overrides[require_operator]=lambda:'operator'
    try:
        with TestClient(app) as transport:
            response=transport.get('/checkout-config?order_id=order_closed')
            assert response.status_code==409
    finally:app.dependency_overrides.clear()
