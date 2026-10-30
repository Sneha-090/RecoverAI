"""Case-wide restrictions must block all actions before ML or provider calls."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.session import Base
from app.models.models import Action, AuditLog, MLPrediction, Payment, RecoveryScore
from app.services.decision import decide
from app.services.eligibility import is_recovery_eligible
from app.services.execution import execute_action, human_review_action


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def make_payment(blocker=None):
    payment = Payment(
        payment_id="pay_case_guard", amount=1000, status="failed",
        razorpay_state="failed", created_at=datetime.utcnow() - timedelta(days=1),
    )
    if blocker == "expired":
        payment.created_at = datetime.utcnow() - timedelta(days=settings.max_recovery_window_days, seconds=1)
    elif blocker:
        field, state = blocker
        setattr(payment, field, state)
    return payment


BLOCKERS = [
    ("status", "captured"), ("status", "authorized"),
    ("status", "recovered"), ("status", "closed_unrecovered"),
    ("razorpay_state", "captured"), ("razorpay_state", "authorized"),
    "expired",
]


@pytest.mark.parametrize("blocker", BLOCKERS)
def test_ineligible_case_skips_before_predictions_or_scoring(db, monkeypatch, blocker):
    payment = make_payment(blocker)
    db.add(payment)
    db.commit()
    predict = Mock(side_effect=AssertionError("Blocked case must not use ML"))
    monkeypatch.setattr("app.services.decision.predict_all_actions", predict)

    result = decide(db, payment)

    assert result["decision_type"] == "skip"
    assert result["chosen_action"] is None
    assert "recovery not attempted" in result["reason"]
    predict.assert_not_called()
    assert db.query(MLPrediction).count() == 0
    assert db.query(RecoveryScore).count() == 0
    assert execute_action(db, payment)["executed"] is False
    assert db.query(Action).count() == 0
    assert db.query(AuditLog).one().reason == result["reason"]


@pytest.mark.parametrize("action", ["retry", "payment_link", "alt_method"])
@pytest.mark.parametrize("blocker", BLOCKERS)
def test_automatic_execution_rechecks_case_after_decision(db, monkeypatch, action, blocker):
    payment = make_payment(blocker)
    db.add(payment)
    db.commit()
    monkeypatch.setattr("app.services.execution.decide", lambda *args: {
        "chosen_action": action, "decision_type": "auto", "reason": "earlier decision",
    })
    order = Mock(side_effect=AssertionError("Must not create order"))
    link = Mock(side_effect=AssertionError("Must not create link"))
    monkeypatch.setattr("app.services.execution.create_test_order", order)
    monkeypatch.setattr("app.services.execution.create_payment_link", link)

    result = execute_action(db, payment)

    assert result["executed"] is False
    assert result["decision_type"] == "skip"
    assert db.query(Action).count() == 0
    assert db.query(AuditLog).one().event_type == "skipped"
    order.assert_not_called()
    link.assert_not_called()


@pytest.mark.parametrize("action", ["retry", "payment_link", "alt_method"])
@pytest.mark.parametrize("blocker", BLOCKERS)
def test_human_approval_cannot_bypass_case_restrictions(db, monkeypatch, action, blocker):
    payment = make_payment(blocker)
    review = Action(
        payment_id=payment.payment_id, action_type=action,
        decision_type="human_review", review_status="pending",
        review_deadline=datetime.utcnow() + timedelta(hours=1),
    )
    db.add_all([payment, review])
    db.commit()
    order = Mock(side_effect=AssertionError("Must not create order"))
    link = Mock(side_effect=AssertionError("Must not create link"))
    monkeypatch.setattr("app.services.execution.create_test_order", order)
    monkeypatch.setattr("app.services.execution.create_payment_link", link)

    result = human_review_action(db, payment.payment_id, action)

    assert result["success"] is False
    assert "recovery not attempted" in result["reason"]
    assert review.review_status == "pending"
    assert db.query(Action).count() == 1
    assert db.query(AuditLog).one().event_type == "human_review_blocked"
    order.assert_not_called()
    link.assert_not_called()


@pytest.mark.parametrize("action", ["retry", "payment_link", "alt_method"])
def test_eligible_failed_case_can_still_execute(db, monkeypatch, action):
    payment = make_payment()
    db.add(payment)
    db.commit()
    monkeypatch.setattr("app.services.decision.predict_all_actions", lambda *args: {
        candidate: 0.9 if candidate == action else 0.1
        for candidate in ["retry", "payment_link", "alt_method"]
    })
    order = Mock(return_value={"id": "order_test"})
    link = Mock(return_value={"id": "plink_test", "short_url": "https://example.com/test"})
    monkeypatch.setattr("app.services.execution.create_test_order", order)
    monkeypatch.setattr("app.services.execution.create_payment_link", link)

    result = execute_action(db, payment)

    assert result["executed"] is True
    assert result["chosen_action"] == action
    assert db.query(Action).one().action_type == action


def test_halted_case_still_allows_customer_assisted_recovery(db, monkeypatch):
    payment = make_payment()
    payment.razorpay_state = "halted"
    monkeypatch.setattr("app.services.decision.predict_all_actions", lambda *args: {
        "retry": 0.99, "payment_link": 0.9, "alt_method": 0.1,
    })
    assert decide(db, payment)["chosen_action"] == "payment_link"


@pytest.mark.parametrize("offset, eligible", [(-1, True), (0, False), (1, False)])
@pytest.mark.parametrize("aware", [False, True])
def test_exact_recovery_window_boundary(monkeypatch, offset, eligible, aware):
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)

    monkeypatch.setattr("app.services.eligibility.datetime", FrozenDatetime)
    payment = make_payment()
    created_at = now - timedelta(days=settings.max_recovery_window_days, seconds=offset)
    payment.created_at = created_at if aware else created_at.replace(tzinfo=None)
    assert is_recovery_eligible(payment)[0] is eligible


def test_missing_creation_time_blocks_recovery():
    payment = make_payment()
    payment.created_at = None
    assert is_recovery_eligible(payment)[0] is False
