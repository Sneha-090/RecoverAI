from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import (Payment, Action, MLPrediction, RecoveryScore, RecoveryIntent,
                               RecoveryReservation)
from app.services.execution import execute_action
from app.services.ml_service import predict_recovery, supported_recovery_causes, UnsupportedRecoveryCause


@pytest.fixture
def coverage_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        yield db
    engine.dispose()


@pytest.mark.parametrize('reason', [None, 'payment_failed', 'new_provider_reason',
    'expired_card', 'invalid_card', 'authentication_failed', 'payment_cancelled'])
def test_untrained_or_unknown_cause_waits_for_assessment_without_predictions_or_provider(coverage_db, monkeypatch, reason):
    db = coverage_db
    payment = Payment(payment_id='pay_unknown', amount=499, payment_method='card', status='failed',
                      razorpay_state='failed', razorpay_error_code='BAD_REQUEST_ERROR',
                      razorpay_error_reason=reason)
    db.add(payment); db.commit()
    forbidden = Mock(side_effect=AssertionError('Unsupported input must not use ML or create resources'))
    monkeypatch.setattr('app.services.decision.predict_all_actions', forbidden)
    monkeypatch.setattr('app.services.execution.create_test_order', forbidden)
    monkeypatch.setattr('app.services.execution.create_payment_link', forbidden)
    result = execute_action(db, payment)
    assert result['decision_type'] == 'human_review'
    assert result['chosen_action'] == 'manual_assessment'
    assert result['executed'] is False
    assert 'outside the model' in result['reason']
    assert db.query(MLPrediction).count() == db.query(RecoveryScore).count() == 0
    assert db.query(RecoveryIntent).count() == 0
    assert db.get(RecoveryReservation, payment.payment_id).state == 'pending_review'
    review = db.query(Action).one()
    assert review.action_type == 'manual_assessment' and review.review_status.value == 'pending'
    assert execute_action(db, payment)['status'] == 'already_processing'
    assert db.query(Action).count() == 1
    forbidden.assert_not_called()


@pytest.mark.parametrize('reason,action', [('payment_declined','payment_link'),
    ('insufficient_funds','alt_method'), ('gateway_technical_error','retry')])
def test_supported_causes_keep_distinct_automatic_actions(coverage_db, monkeypatch, reason, action):
    db = coverage_db
    payment = Payment(payment_id='pay_known', amount=499, payment_method='card', status='failed', razorpay_state='failed',
                      razorpay_error_reason=reason)
    db.add(payment); db.commit()
    order = Mock(return_value={'id':'order_known'})
    link = Mock(return_value={'id':'plink_known','short_url':'https://example.invalid/known'})
    monkeypatch.setattr('app.services.execution.create_test_order', order)
    monkeypatch.setattr('app.services.execution.create_payment_link', link)
    result = execute_action(db, payment)
    assert result['executed'] is True and result['chosen_action'] == action
    assert db.query(MLPrediction).count() == db.query(RecoveryScore).count() == 3
    assert order.call_count + link.call_count == 1


def test_direct_prediction_cannot_silently_encode_unknown_cause():
    with pytest.raises(UnsupportedRecoveryCause):
        predict_recovery(499, 'never_trained', 0, 0, .5, 'payment_link')


def test_coverage_comes_from_fitted_action_interactions(monkeypatch):
    encoder = SimpleNamespace(categories_=[['complete','partial'],
        ['retry','payment_link','alt_method'],
        ['complete__retry','complete__payment_link','complete__alt_method','partial__retry']])
    fake = SimpleNamespace(named_steps={'preprocessor':SimpleNamespace(named_transformers_={'categorical':encoder})})
    monkeypatch.setattr('app.services.ml_service.model', fake)
    assert supported_recovery_causes() == frozenset({'complete'})



@pytest.mark.parametrize('amount', [1,20000,88000])
def test_outside_numeric_training_support_requires_assessment_without_provider(coverage_db,monkeypatch,amount):
    payment=Payment(payment_id='pay_outside',amount=amount,status='failed',razorpay_state='failed',
                    payment_method='card',razorpay_error_reason='insufficient_funds')
    coverage_db.add(payment);coverage_db.commit()
    forbidden=Mock(side_effect=AssertionError('Outside support must not create a resource'))
    monkeypatch.setattr('app.services.execution.create_test_order',forbidden)
    monkeypatch.setattr('app.services.execution.create_payment_link',forbidden)
    result=execute_action(coverage_db,payment)
    assert result['chosen_action']=='manual_assessment' and result['executed'] is False
    assert coverage_db.query(MLPrediction).count()==0
    forbidden.assert_not_called()
