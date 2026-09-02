"""
Module A verification: confirms decide()/execute_action() now persist
ML predictions, recovery scores, and the decision reason - without
changing the actual decision.

Uses a Rs.88,000 payment (guaranteed human_review, per the >Rs.50,000
threshold) specifically so this test never triggers a real Razorpay
API call - it stays a clean, network-free unit test.
"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Payment, Diagnosis, MLPrediction, RecoveryScore, Action
from app.services.execution import execute_action


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_module_a_persists_predictions_scores_and_reason():
    db = make_session()

    payment = Payment(
        payment_id="pay_module_a_test",
        amount=88000.0,
        payment_method="card",
        razorpay_error_code="BAD_REQUEST_ERROR",
        razorpay_error_reason="payment_failed",
        razorpay_state="failed",
        status="failed",
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add(payment)
    db.commit()

    diagnosis = Diagnosis(payment_id=payment.payment_id, cause="bank_declined", diagnosed_at=datetime.utcnow())
    db.add(diagnosis)
    db.commit()

    result = execute_action(db, payment)

    # Decision behavior must be exactly what we expect for a high-value payment
    assert result["decision_type"] == "human_review"
    assert result["executed"] is False

    # A. ML predictions persisted for all 3 actions
    predictions = db.query(MLPrediction).filter(MLPrediction.payment_id == payment.payment_id).all()
    assert len(predictions) == 3
    assert {p.action_type for p in predictions} == {"retry", "payment_link", "alt_method"}

    # B. Recovery scores persisted for all 3 actions
    scores = db.query(RecoveryScore).filter(RecoveryScore.payment_id == payment.payment_id).all()
    assert len(scores) == 3
    assert all(s.eligibility_reason is not None for s in scores)

    # D. Decision reason persisted on the Action row, matches what was returned
    action_row = db.query(Action).filter(Action.payment_id == payment.payment_id).first()
    assert action_row.reason is not None
    assert action_row.reason == result["reason"]