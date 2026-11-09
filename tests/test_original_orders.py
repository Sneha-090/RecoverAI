from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from alembic import command

from app.db.session import Base
from app.db.schema import migration_config, migrate_database
from app.models.models import Action, OriginalOrderRecovery, Payment, RecoveryExecution
from app.services.original_orders import bind_original_order, original_order_eligibility
from app.services.execution import execute_action, human_review_action


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path/'orders.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        now = datetime.utcnow()
        db.add_all([Payment(payment_id='pay_first', order_id='order_original', amount=499,
                            status='failed', razorpay_state='failed', created_at=now-timedelta(minutes=1)),
                    Payment(payment_id='pay_second', order_id='order_original', amount=499,
                            status='failed', razorpay_state='failed', created_at=now)])
        db.commit()
    monkeypatch.setattr('app.services.execution.decide', lambda *_: {
        'chosen_action':'payment_link','decision_type':'auto','reason':'fixture'})
    yield factory
    engine.dispose()


def test_simultaneous_distinct_failures_for_one_order_create_one_recovery(sessions,monkeypatch):
    provider=Mock(return_value={'id':'plink_only'})
    monkeypatch.setattr('app.services.execution.create_payment_link',provider)
    barrier=Barrier(2)
    def process(payment_id):
        with sessions() as db:
            payment=db.get(Payment,payment_id)
            barrier.wait(timeout=10)
            return execute_action(db,payment)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(process,['pay_first','pay_second']))
    assert sum(r['executed'] for r in results)==1
    assert provider.call_count==1
    with sessions() as db:
        scope=db.get(OriginalOrderRecovery,'order_original')
        assert scope.payment_id=='pay_first' and scope.state=='active'
        assert db.query(RecoveryExecution).one().payment_id=='pay_first'
    # Restart / new session cannot give the second payment a new recovery budget.
    with sessions() as db:
        assert not execute_action(db,db.get(Payment,'pay_second'))['executed']
    assert provider.call_count==1


def test_closed_owner_is_not_reassigned_to_a_new_failed_attempt(sessions,monkeypatch):
    provider=Mock(side_effect=AssertionError('No resource allowed'))
    monkeypatch.setattr('app.services.execution.create_payment_link',provider)
    with sessions() as db:
        first=db.get(Payment,'pay_first')
        bind_original_order(db,first)
        first.status='closed_unrecovered';db.commit()
        result=execute_action(db,db.get(Payment,'pay_second'))
        assert not result['executed'] and 'pay_first' in result['reason']
    provider.assert_not_called()


def test_secondary_case_cannot_be_approved_even_with_a_later_review(sessions,monkeypatch):
    provider=Mock(side_effect=AssertionError('No resource allowed'))
    monkeypatch.setattr('app.services.execution.create_payment_link',provider)
    with sessions() as db:
        bind_original_order(db,db.get(Payment,'pay_first'))
        db.add(Action(payment_id='pay_second',action_type='payment_link',decision_type='human_review',
                      review_status='pending',review_deadline=datetime.utcnow()+timedelta(hours=1)))
        db.commit()
        result=human_review_action(db,'pay_second','payment_link')
        assert not result['success'] and 'pay_first' in result['reason']
    provider.assert_not_called()


def test_legacy_multiple_acted_cases_block_all_new_recovery(sessions):
    with sessions() as db:
        for payment_id in ('pay_first','pay_second'):
            db.add(Action(payment_id=payment_id,action_type='retry',decision_type='auto'))
        db.commit()
        for payment_id in ('pay_first','pay_second'):
            assert not original_order_eligibility(db,db.get(Payment,payment_id))[0]
        row=db.get(OriginalOrderRecovery,'order_original')
        assert row.state=='ambiguous' and row.payment_id is None


@pytest.mark.parametrize('multiple',[False,True])
def test_migration_retains_prior_work_and_blocks_ambiguous_owners(tmp_path,multiple):
    engine=create_engine(f"sqlite:///{(tmp_path/'legacy.sqlite').as_posix()}")
    with engine.begin() as connection:
        command.upgrade(migration_config(connection),'0001')
        for payment_id in ('pay_first','pay_second'):
            connection.execute(text("INSERT INTO payments (payment_id,order_id,amount,status) VALUES (:id,'order_shared',499,'failed')"),{'id':payment_id})
        for payment_id in (('pay_first','pay_second') if multiple else ('pay_second',)):
            connection.execute(text("INSERT INTO actions (payment_id,action_type,decision_type) VALUES (:id,'retry','auto')"),{'id':payment_id})
    assert migrate_database(engine,backup_directory=tmp_path/'backup')['backup_created']
    with sessionmaker(bind=engine)() as db:
        row=db.get(OriginalOrderRecovery,'order_shared')
        assert row.state==('ambiguous' if multiple else 'active')
        assert row.payment_id==(None if multiple else 'pay_second')
        assert db.query(Payment).count()==2
        assert db.query(Action).count()==(2 if multiple else 1)
    engine.dispose()


def test_ingestion_refuses_a_changed_original_order(sessions,monkeypatch):
    from app.services.ingestion import fetch_and_store_payment
    monkeypatch.setattr('app.services.ingestion.client.payment.fetch',lambda _: {
        'id':'pay_first','order_id':'order_changed','amount':49900,'status':'failed'})
    with sessions() as db:
        with pytest.raises(ValueError,match='order reference changed'):
            fetch_and_store_payment(db,'pay_first')
        assert db.get(Payment,'pay_first').order_id=='order_original'
