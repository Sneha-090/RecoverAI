from datetime import datetime, timedelta

from app.services.eligibility import is_retry_eligible
from app.models.models import Payment, Action


class FakeQuery:
    """Minimal fake to test eligibility logic without a real DB session."""
    def __init__(self, actions):
        self._actions = actions

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return len(self._actions)

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._actions[-1] if self._actions else None


class FakeDB:
    def __init__(self, actions):
        self._actions = actions

    def query(self, model):
        return FakeQuery(self._actions)


def make_payment(state="failed", created_days_ago=0):
    return Payment(
        payment_id="pay_test",
        amount=499,
        razorpay_state=state,
        created_at=datetime.utcnow() - timedelta(days=created_days_ago),
    )


def test_halted_subscription_is_not_eligible():
    db = FakeDB(actions=[])
    p = make_payment(state="halted")
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is False
    assert "halted" in reason


def test_captured_payment_is_not_eligible():
    db = FakeDB(actions=[])
    p = make_payment(state="captured")
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is False


def test_fresh_failed_payment_is_eligible():
    db = FakeDB(actions=[])
    p = make_payment(state="failed", created_days_ago=1)
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is True


def test_exceeds_recovery_window():
    db = FakeDB(actions=[])
    p = make_payment(state="failed", created_days_ago=20)
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is False
    assert "recovery window" in reason


def test_max_attempts_exceeded():
    old_action = Action(action_type="retry", chosen_at=datetime.utcnow() - timedelta(hours=10))
    db = FakeDB(actions=[old_action, old_action, old_action])  # 3 retries used
    p = make_payment(state="failed", created_days_ago=1)
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is False
    assert "max retry attempts" in reason


def test_cooling_off_blocks_recent_retry():
    recent_action = Action(action_type="retry", chosen_at=datetime.utcnow() - timedelta(hours=1))
    db = FakeDB(actions=[recent_action])
    p = make_payment(state="failed", created_days_ago=1)
    eligible, reason = is_retry_eligible(db, p)
    assert eligible is False
    assert "cooling-off" in reason