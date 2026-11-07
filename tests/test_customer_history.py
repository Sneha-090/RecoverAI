from datetime import datetime,timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Payment,Customer,Outcome,AuditLog
from app.services.customer_history import customer_history
from app.services.ingestion import fetch_and_store_payment
from app.services.decision import decide


@pytest.fixture
def history_db():
    engine=create_engine('sqlite:///:memory:'); Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        yield db
    engine.dispose()


def test_history_counts_finalized_cases_once_and_excludes_unavailable_evidence(history_db):
    db=history_db; now=datetime.utcnow()
    db.add_all([Customer(customer_id='cust_A'),Customer(customer_id='cust_B')])
    for pid,status,customer in [('pay_current','recovered','cust_A'),('pay_good','recovered','cust_A'),
        ('pay_closed','closed_unrecovered','cust_A'),('pay_pending','failed','cust_A'),
        ('pay_other','recovered','cust_B'),('pay_future','recovered','cust_A'),('pay_unsupported','recovered','cust_A')]:
        db.add(Payment(payment_id=pid,amount=499,status=status,customer_id=customer,created_at=now-timedelta(days=1)))
    db.add_all([
        Outcome(payment_id='pay_good',action_type='payment_link',observed_result='success',observed_at=now),
        Outcome(payment_id='pay_good',action_type='retry',observed_result='success',observed_at=now),
        Outcome(payment_id='pay_current',action_type='retry',observed_result='success',observed_at=now),
        Outcome(payment_id='pay_other',action_type='retry',observed_result='success',observed_at=now),
        Outcome(payment_id='pay_future',action_type='retry',observed_result='success',observed_at=now+timedelta(days=1)),
        AuditLog(payment_id='pay_closed',event_type='human_review_expired',timestamp=now),
    ]);db.commit()
    result=customer_history(db,'cust_A','pay_current',as_of=now)
    assert result['finalized_cases']==2 and result['recovered_cases']==1
    assert result['past_rate']==.5 and result['uses_default'] is False
    assert customer_history(db,None)['uses_default'] is True
    assert customer_history(db,'cust_missing')['uses_default'] is True


def test_provider_customer_is_linked_idempotently_without_contact_matching(history_db,monkeypatch):
    payload={'id':'pay_ingested','amount':49900,'status':'failed','customer_id':'cust_Verified',
             'method':'card','error_reason':'insufficient_funds','email':'not-used@example.invalid'}
    monkeypatch.setattr('app.services.ingestion.client.payment.fetch',lambda _:payload)
    for _ in range(2):
        assert fetch_and_store_payment(history_db,'pay_ingested').customer_id=='cust_Verified'
    assert history_db.query(Customer).count()==1
    assert history_db.query(Payment).count()==1
    payload['customer_id']='cust_Different'
    with pytest.raises(ValueError,match='changed'):
        fetch_and_store_payment(history_db,'pay_ingested')
    assert history_db.get(Payment,'pay_ingested').customer_id=='cust_Verified'


def test_new_decision_records_the_actual_history_features(history_db):
    db=history_db; db.add(Customer(customer_id='cust_A'));db.flush()
    db.add_all([Payment(payment_id='pay_past',amount=499,status='recovered',customer_id='cust_A'),
                Payment(payment_id='pay_current',amount=499,status='failed',razorpay_state='failed',
                        customer_id='cust_A',payment_method='card',razorpay_error_reason='insufficient_funds')])
    db.add(Outcome(payment_id='pay_past',action_type='retry',observed_result='success'))
    db.commit();decide(db,db.get(Payment,'pay_current'))
    import json
    snapshot=json.loads(db.query(AuditLog).filter_by(event_type='decision_features').one().payload_json)
    assert snapshot['past_rate']==1 and snapshot['history_cases']==1
    assert snapshot['executed_attempts']==0 and snapshot['uses_default_history'] is False
    assert 'customer_id' not in snapshot



@pytest.mark.parametrize('customer_id',['person@example.invalid',123,'cust_../bad'])
def test_invalid_provider_identity_does_not_create_or_link_records(history_db,monkeypatch,customer_id):
    monkeypatch.setattr('app.services.ingestion.client.payment.fetch',lambda _: {
        'id':'pay_invalid','amount':49900,'status':'failed','customer_id':customer_id})
    with pytest.raises(ValueError,match='invalid'):
        fetch_and_store_payment(history_db,'pay_invalid')
    assert history_db.query(Customer).count()==history_db.query(Payment).count()==0
