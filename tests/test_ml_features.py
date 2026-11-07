from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Action, Payment
from app.services.ml_service import predict_all_actions


@pytest.mark.parametrize('review_status', ['pending', 'actioned', 'expired'])
def test_review_recommendation_does_not_change_model_predictions(review_status):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        payment = Payment(payment_id='pay_features', amount=499, status='failed',
                          razorpay_error_reason='insufficient_funds',
                          created_at=datetime.utcnow()-timedelta(hours=1))
        db.add(payment)
        db.commit()
        before = predict_all_actions(db, payment)
        db.add(Action(payment_id=payment.payment_id, action_type='retry',
                      decision_type='human_review', review_status=review_status))
        db.commit()
        assert predict_all_actions(db, payment) == before
    engine.dispose()


def test_approved_execution_counts_once_and_other_cases_are_excluded(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        payment = Payment(payment_id='pay_features', amount=499, status='failed',
                          razorpay_error_reason='insufficient_funds', created_at=datetime.utcnow())
        db.add_all([payment, Payment(payment_id='pay_other', amount=499)])
        db.add_all([
            Action(payment_id=payment.payment_id, action_type='retry',
                   decision_type='human_review', review_status='actioned'),
            Action(payment_id=payment.payment_id, action_type='retry', decision_type='auto'),
            Action(payment_id='pay_other', action_type='retry', decision_type='auto'),
        ])
        db.commit()
        predict = Mock(return_value=0.8)
        monkeypatch.setattr('app.services.ml_service.predict_recovery', predict)
        assert len(predict_all_actions(db, payment)) == 3
        assert predict.call_count == 3
        assert all(call.kwargs['attempts'] == 1 for call in predict.call_args_list)
    engine.dispose()
