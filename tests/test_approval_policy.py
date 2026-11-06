from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.session import Base
from app.models.models import Action, Payment, AuditLog, RecoveryReservation
from app.services.execution import human_review_action
from app.services.eligibility import is_retry_eligible


@pytest.fixture
def approval_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Payment(payment_id='pay_policy', amount=499, status='failed', razorpay_state='failed'))
        db.commit()
        yield db
    engine.dispose()


def pending_review(db, chosen='retry'):
    row = Action(payment_id='pay_policy', action_type=chosen, decision_type='human_review',
                 review_status='pending', review_deadline=datetime.utcnow()+timedelta(hours=1))
    db.add(row)
    db.add(RecoveryReservation(payment_id='pay_policy', owner='waiting', state='pending_review'))
    db.commit()
    return row


@pytest.mark.parametrize('chosen', ['retry', 'payment_link', 'alt_method'])
def test_human_approval_cannot_repeat_an_executed_action(approval_db, monkeypatch, chosen):
    db = approval_db
    db.add(Action(payment_id='pay_policy', action_type=chosen, decision_type='auto',
                  chosen_at=datetime.utcnow()-timedelta(hours=12)))
    review = pending_review(db, chosen)
    provider = Mock(side_effect=AssertionError('Previously executed action must not be repeated'))
    monkeypatch.setattr('app.services.execution.create_test_order', provider)
    monkeypatch.setattr('app.services.execution.create_payment_link', provider)
    result = human_review_action(db, 'pay_policy', chosen)
    assert result['success'] is False and 'already executed' in result['reason']
    assert db.get(RecoveryReservation, 'pay_policy').state == 'pending_review'
    db.refresh(review)
    assert review.review_status.value == 'pending'
    assert db.query(AuditLog).filter_by(event_type='human_review_blocked').count() == 1
    provider.assert_not_called()


@pytest.mark.parametrize('status', ['pending', 'actioned', 'expired'])
def test_review_recommendations_do_not_consume_retry_budget_or_cooling_off(approval_db, monkeypatch, status):
    db = approval_db
    monkeypatch.setattr(settings, 'max_retry_attempts', 1)
    monkeypatch.setattr(settings, 'retry_cooling_off_hours', 24)
    db.add(Action(payment_id='pay_policy', action_type='retry', decision_type='human_review',
                  review_status=status, chosen_at=datetime.utcnow()))
    db.commit()
    assert is_retry_eligible(db, db.get(Payment, 'pay_policy')) == (True, 'retry eligible')


def test_approved_first_retry_is_not_blocked_by_its_own_pending_recommendation(approval_db, monkeypatch):
    db = approval_db
    monkeypatch.setattr(settings, 'max_retry_attempts', 1)
    monkeypatch.setattr(settings, 'retry_cooling_off_hours', 24)
    pending_review(db, 'retry')
    provider = Mock(return_value={'id': 'order_first_retry'})
    monkeypatch.setattr('app.services.execution.create_test_order', provider)
    result = human_review_action(db, 'pay_policy', 'retry')
    assert result['success'] is True
    assert provider.call_count == 1
    assert db.query(Action).filter_by(decision_type='auto', action_type='retry').count() == 1


@pytest.mark.parametrize('hours,max_attempts,reason', [(12, 1, 'max retry attempts'), (1, 3, 'cooling-off')])
def test_executed_retry_still_enforces_limits(approval_db, monkeypatch, hours, max_attempts, reason):
    db = approval_db
    monkeypatch.setattr(settings, 'max_retry_attempts', max_attempts)
    db.add(Action(payment_id='pay_policy', action_type='retry', decision_type='auto',
                  chosen_at=datetime.utcnow()-timedelta(hours=hours)))
    db.commit()
    eligible, message = is_retry_eligible(db, db.get(Payment, 'pay_policy'))
    assert eligible is False and reason in message


def test_human_can_choose_an_untried_action_after_a_different_action_was_executed(approval_db, monkeypatch):
    db = approval_db
    db.add(Action(payment_id='pay_policy', action_type='payment_link', decision_type='auto',
                  chosen_at=datetime.utcnow()-timedelta(hours=12)))
    pending_review(db, 'alt_method')
    provider = Mock(return_value={'id': 'plink_alternate'})
    monkeypatch.setattr('app.services.execution.create_payment_link', provider)
    assert human_review_action(db, 'pay_policy', 'alt_method')['success'] is True
    assert provider.call_count == 1
