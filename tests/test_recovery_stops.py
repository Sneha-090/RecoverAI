from datetime import datetime,timedelta
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from alembic import command
from app.db.session import Base
from app.db.schema import migration_config,migrate_database
from app.models.models import Payment,Action,RecoveryReservation,AuditLog,OriginalOrderRecovery
from app.services.recovery_stops import stop_followup,REASONS
from app.services.execution import execute_action,human_review_action


@pytest.fixture
def sessions(tmp_path,monkeypatch):
    engine=create_engine(f"sqlite:///{(tmp_path/'stop.sqlite').as_posix()}")
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add(Payment(payment_id='pay_stop',amount=499,status='failed',razorpay_state='failed'));db.commit()
    create=Mock(side_effect=AssertionError('No resource permitted'))
    monkeypatch.setattr('app.services.execution.create_payment_link',create)
    monkeypatch.setattr('app.services.execution.create_test_order',create)
    yield factory,create
    engine.dispose()


@pytest.mark.parametrize('reason',list(REASONS))
def test_stop_survives_new_sessions_and_blocks_auto_and_approval(sessions,reason):
    factory,create=sessions
    with factory() as db:
        db.add(Action(payment_id='pay_stop',action_type='payment_link',decision_type='human_review',
                      review_status='pending',review_deadline=datetime.utcnow()+timedelta(hours=1)));db.commit()
        assert stop_followup(db,'pay_stop','operator',reason)['status']=='stopped'
    with factory() as db:
        p=db.get(Payment,'pay_stop')
        assert p.recovery_stop_reason==reason and p.recovery_stopped_at
        assert not execute_action(db,p)['executed']
        assert not human_review_action(db,'pay_stop','payment_link')['success']
        assert db.query(Action).one().review_status=='expired'
        assert db.get(RecoveryReservation,'pay_stop') is None
    create.assert_not_called()


def test_group_stop_protects_other_attempts_without_stealing_processing_claim(sessions):
    factory,create=sessions
    with factory() as db:
        p=db.get(Payment,'pay_stop');p.order_id='order_shared'
        db.add(Payment(payment_id='pay_second',order_id='order_shared',amount=499,status='failed'))
        db.add(RecoveryReservation(payment_id='pay_stop',owner='in-flight-owner',state='processing'));db.commit()
        result=stop_followup(db,'pay_second','operator','customer_opt_out')
        assert result['status']=='stop_recorded'
        assert db.get(RecoveryReservation,'pay_stop').owner=='in-flight-owner'
        assert db.get(OriginalOrderRecovery,'order_shared').state=='operator_stopped'
        assert all(p.recovery_stop_reason for p in db.query(Payment).all())
        assert not execute_action(db,db.get(Payment,'pay_second'))['executed']
    create.assert_not_called()


def test_stop_during_scoring_blocks_provider_creation(sessions,monkeypatch):
    factory,create=sessions
    def decide(*_):
        with factory() as other:stop_followup(other,'pay_stop','operator','fraud_concern')
        return {'chosen_action':'payment_link','decision_type':'auto','reason':'fixture'}
    monkeypatch.setattr('app.services.execution.decide',decide)
    with factory() as db:
        assert execute_action(db,db.get(Payment,'pay_stop'))['status']=='followup_stopped'
        assert db.get(RecoveryReservation,'pay_stop') is None
    create.assert_not_called()


def test_idempotent_stop_preserves_original_reason_and_one_audit(sessions):
    factory,_=sessions
    with factory() as db:
        stop_followup(db,'pay_stop','operator','customer_opt_out')
        stop_followup(db,'pay_stop','operator','operator_stop')
        assert db.get(Payment,'pay_stop').recovery_stop_reason=='customer_opt_out'
        assert db.query(AuditLog).filter_by(event_type='followup_stopped').count()==1


@pytest.mark.parametrize('state',['created','pending','refunded','unknown'])
def test_nonfailed_payment_never_qualifies_for_new_collection(sessions,state):
    from app.services.eligibility import is_recovery_eligible
    factory,create=sessions
    with factory() as db:
        p=db.get(Payment,'pay_stop');p.status=state;p.razorpay_state=state;db.commit()
        assert not is_recovery_eligible(p)[0]
        assert not execute_action(db,p)['executed']
    create.assert_not_called()


def test_upgrade_retains_case_and_adds_stop_fields(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'upgrade.sqlite').as_posix()}")
    with engine.begin() as c:
        command.upgrade(migration_config(c),'0002')
        c.execute(text("INSERT INTO payments (payment_id,amount,status) VALUES ('pay_keep',499,'failed')"))
    migrate_database(engine,backup_directory=tmp_path/'backup')
    with sessionmaker(bind=engine)() as db:
        p=db.get(Payment,'pay_keep')
        assert p.amount==499 and p.recovery_stop_reason is None
    engine.dispose()
