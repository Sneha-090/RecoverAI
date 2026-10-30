from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.models import Action, Outcome, Payment, RecoveryReservation
from app.services.execution import execute_action, human_review_action, observe_outcome
from app.services.reservations import RecoveryInProgress


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'execution.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Payment(payment_id="pay_shared", amount=1000, status="failed", razorpay_state="failed"))
        db.commit()
    monkeypatch.setattr("app.services.execution.decide", lambda *args: {
        "chosen_action": "payment_link", "decision_type": "auto", "reason": "test decision",
    })
    yield factory
    engine.dispose()


def run_auto(sessions):
    with sessions() as db:
        return execute_action(db, db.get(Payment, "pay_shared"))


@pytest.mark.parametrize("human", [False, True])
def test_overlapping_automatic_and_human_requests_create_one_link(sessions, monkeypatch, human):
    started, release = Event(), Event()

    def create(*args, **kwargs):
        started.set()
        assert release.wait(timeout=10)
        return {"id": "plink_one"}

    provider = Mock(side_effect=create)
    monkeypatch.setattr("app.services.execution.create_payment_link", provider)
    if human:
        with sessions() as db:
            db.add(Action(
                payment_id="pay_shared", action_type="payment_link", decision_type="human_review",
                review_status="pending", review_deadline=datetime.utcnow() + timedelta(hours=1),
            ))
            db.commit()

    def first():
        if not human:
            return run_auto(sessions)
        with sessions() as db:
            return human_review_action(db, "pay_shared", "payment_link")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first)
        try:
            assert started.wait(timeout=10)
            assert run_auto(sessions)["executed"] is False
            with sessions() as db:
                assert human_review_action(db, "pay_shared", "alt_method")["success"] is False
        finally:
            release.set()
        result = future.result(timeout=10)
    assert result.get("executed", result.get("success")) is True
    assert provider.call_count == 1
    # A restart/new session must not start another action while awaiting payment.
    assert run_auto(sessions)["executed"] is False
    assert provider.call_count == 1


@pytest.mark.parametrize("fail_after_provider", [False, True])
def test_uncertain_execution_stays_blocked_after_restart(sessions, monkeypatch, fail_after_provider):
    provider = Mock(return_value={"id": "plink_maybe_created"})
    if fail_after_provider:
        monkeypatch.setattr("app.services.execution._log_audit", Mock(side_effect=RuntimeError("lost DB write")))
    else:
        provider.side_effect = TimeoutError("provider may have accepted request")
    monkeypatch.setattr("app.services.execution.create_payment_link", provider)
    with pytest.raises((TimeoutError, RuntimeError)):
        run_auto(sessions)
    with sessions() as db:
        assert db.get(RecoveryReservation, "pay_shared").state == "needs_reconciliation"
    assert run_auto(sessions)["executed"] is False
    assert provider.call_count == 1


def test_pending_link_retains_reservation_without_new_action(sessions, monkeypatch):
    provider = Mock(return_value={"id": "plink_pending"})
    monkeypatch.setattr("app.services.execution.create_payment_link", provider)
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda _: {"status": "created"})
    run_auto(sessions)
    with sessions() as db:
        result = observe_outcome(db, db.get(Payment, "pay_shared"))
        assert result["status"] == "awaiting_outcome"
        assert db.query(Outcome).count() == 0
        assert db.get(RecoveryReservation, "pay_shared").state == "awaiting_outcome"
    assert provider.call_count == 1


def test_old_webhook_does_not_observe_newer_attempt(sessions, monkeypatch):
    monkeypatch.setattr("app.services.execution.create_payment_link", lambda *a, **k: {"id": "plink_current"})
    check = Mock(side_effect=AssertionError("Wrong attempt must not be observed"))
    monkeypatch.setattr("app.services.execution._check_real_outcome", check)
    run_auto(sessions)
    with sessions() as db:
        result = observe_outcome(db, db.get(Payment, "pay_shared"), expected_order_id="order_old")
        assert result["status"] == "awaiting_outcome"
        assert db.query(Outcome).count() == 0
        assert db.get(RecoveryReservation, "pay_shared").state == "awaiting_outcome"
    check.assert_not_called()


def test_two_outcome_observers_cannot_run_together(sessions, monkeypatch):
    monkeypatch.setattr("app.services.execution.create_payment_link", lambda *a, **k: {"id": "plink_one"})
    run_auto(sessions)
    started, release = Event(), Event()

    def check(payload):
        started.set()
        assert release.wait(timeout=10)
        return "success"

    monkeypatch.setattr("app.services.execution._check_real_outcome", check)

    def observe():
        with sessions() as db:
            return observe_outcome(db, db.get(Payment, "pay_shared"))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(observe)
        try:
            assert started.wait(timeout=10)
            with pytest.raises(RecoveryInProgress):
                observe()
        finally:
            release.set()
        assert future.result(timeout=10)["status"] == "recovered"
    with sessions() as db:
        assert db.query(Outcome).count() == 1


def test_pending_human_review_is_not_escalated_twice(sessions, monkeypatch):
    monkeypatch.setattr("app.services.execution.decide", lambda *args: {
        "chosen_action": "payment_link", "decision_type": "human_review", "reason": "uncertain",
    })
    assert run_auto(sessions)["decision_type"] == "human_review"
    assert run_auto(sessions)["executed"] is False
    with sessions() as db:
        assert db.query(Action).count() == 1


def test_legacy_unobserved_action_blocks_new_execution(sessions, monkeypatch):
    with sessions() as db:
        db.add(Action(payment_id="pay_shared", action_type="retry", decision_type="auto"))
        db.commit()
    provider = Mock(side_effect=AssertionError("Existing attempt is still active"))
    monkeypatch.setattr("app.services.execution.create_payment_link", provider)
    assert run_auto(sessions)["executed"] is False
    provider.assert_not_called()
