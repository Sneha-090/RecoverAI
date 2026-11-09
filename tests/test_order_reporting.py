import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.models.models import Payment,OriginalOrderRecovery
from app.services.order_reporting import build_order_summary


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:yield session
    engine.dispose()


def test_attempts_share_one_recovered_order_amount_and_sources_stay_separate(db):
    db.add_all([Payment(payment_id='pay_A',order_id='order_same',amount=499,status='failed'),
                Payment(payment_id='pay_B',order_id='order_same',amount=499,status='recovered'),
                Payment(payment_id='pay_unlinked',amount=100,status='failed'),
                Payment(payment_id='sim_fixture',order_id='order_sim',amount=9000,status='recovered'),
                Payment(payment_id='payXnot_provider',amount=9999,status='recovered')]);db.commit()
    report=build_order_summary(db)
    assert report['payment_attempts']==3 and report['tracked_groups']==2
    assert report['known_orders']==report['standalone_payments']==1
    assert report['recovered_groups']==1 and report['recovered_amount']==499
    assert build_order_summary(db,'Simulation')['recovered_amount']==9000


@pytest.mark.parametrize('issue',['two_captures','direct_and_recovery','amount_mismatch','ambiguous','wrong_owner','reconciliation'])
def test_uncertain_groups_do_not_inflate_revenue(db,issue):
    first=Payment(payment_id='pay_A',order_id='order_same',amount=499,status='recovered')
    other=Payment(payment_id='pay_B',order_id='order_same',amount=499,status='failed')
    if issue=='two_captures':other.status='recovered'
    if issue=='direct_and_recovery':other.status='paid_original'
    if issue=='amount_mismatch':other.amount=100
    if issue=='reconciliation':other.status='needs_reconciliation'
    db.add_all([first,other]);db.commit()
    if issue in {'ambiguous','wrong_owner'}:
        db.add(OriginalOrderRecovery(order_id='order_same',payment_id='pay_B' if issue=='wrong_owner' else None,
                                     state='active' if issue=='wrong_owner' else 'ambiguous'));db.commit()
    report=build_order_summary(db)
    assert report['tracked_groups']==report['investigation_groups']==1
    assert report['recovered_groups']==report['recovered_amount']==0


def test_original_success_is_counted_separately_once(db):
    db.add_all([Payment(payment_id='pay_A',order_id='order_same',amount=499,status='paid_original'),
                Payment(payment_id='pay_B',order_id='order_same',amount=499,status='failed')]);db.commit()
    report=build_order_summary(db)
    assert report['paid_original_groups']==report['tracked_groups']==1
    assert report['recovered_amount']==0


def test_empty_and_invalid_source(db):
    assert build_order_summary(db)['tracked_groups']==0
    with pytest.raises(ValueError):build_order_summary(db,'All sources')
