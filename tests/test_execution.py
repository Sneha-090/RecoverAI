import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.models import AuditLog, Action, Payment, Outcome
from app.services.execution import (
    _get_last_execution_payload,
    observe_outcome,
)

@pytest.fixture
def db_session():
    # Temporary in-memory database.
    # Real recoverai.db is NOT touched.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_human_approved_execution_payload_is_found(db_session):
    payload = {
        "type": "order",
        "order_id": "order_human_123",
    }

    audit = AuditLog(
        payment_id="pay_123",
        event_type="human_approved_executed",
        payload_json=json.dumps(payload),
    )

    db_session.add(audit)
    db_session.commit()

    result = _get_last_execution_payload(
        db_session,
        "pay_123",
    )

    assert result == payload


def test_latest_human_approved_execution_wins_over_old_auto_execution(db_session):
    old_payload = {
        "type": "order",
        "order_id": "old_retry_order_123",
    }

    new_payload = {
        "type": "order",
        "order_id": "human_retry_order_456",
    }

    old_audit = AuditLog(
        payment_id="pay_456",
        event_type="executed",
        payload_json=json.dumps(old_payload),
    )

    db_session.add(old_audit)
    db_session.commit()

    new_audit = AuditLog(
        payment_id="pay_456",
        event_type="human_approved_executed",
        payload_json=json.dumps(new_payload),
    )

    db_session.add(new_audit)
    db_session.commit()

    result = _get_last_execution_payload(
        db_session,
        "pay_456",
    )

    assert result == new_payload
    assert result["order_id"] == "human_retry_order_456"

   


def test_human_approved_retry_outcome_uses_latest_action(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_human_outcome_123",
        amount=5000,
        status="failed",
    )
    db_session.add(payment)

    action = Action(
        payment_id="pay_human_outcome_123",
        action_type="retry",
        decision_type="auto",
    )
    db_session.add(action)
    db_session.commit()

    payload = {
        "type": "order",
        "order_id": "human_recovery_order_123",
    }

    audit = AuditLog(
        payment_id="pay_human_outcome_123",
        event_type="human_approved_executed",
        payload_json=json.dumps(payload),
    )
    db_session.add(audit)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.execution._check_real_outcome",
        lambda payload: "success",
    )

    result = observe_outcome(db_session, payment)

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_human_outcome_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "retry"
    assert outcome.observed_result == "success"

def test_payment_link_success_marks_original_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_payment_link_success_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_payment_link_success_123",
        action_type="payment_link",
        decision_type="auto",
    )

    audit = AuditLog(
        payment_id="pay_payment_link_success_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_success_123",
                "short_url": "https://rzp.io/rzp/success123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_success_123"
        return {
            "id": "plink_success_123",
            "status": "paid",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_payment_link_success_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "payment_link"
    assert outcome.observed_result == "success"
def test_payment_link_failed_does_not_mark_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_payment_link_failed_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_payment_link_failed_123",
        action_type="payment_link",
        decision_type="auto",
    )

    audit = AuditLog(
        payment_id="pay_payment_link_failed_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_failed_123",
                "short_url": "https://rzp.io/rzp/failed123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_failed_123"
        return {
            "id": "plink_failed_123",
            "status": "created",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    # Force the next decision so the test does not make a real
    # Razorpay order/payment-link call.
    monkeypatch.setattr(
        "app.services.execution.execute_action",
        lambda db, payment: {
            "chosen_action": None,
            "decision_type": "skip",
            "reason": "no remaining action for test",
            "executed": False,
        },
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_payment_link_failed_123"
        )
        .first()
    )

    assert result["status"] == "closed_unrecovered"
    assert payment.status == "closed_unrecovered"
    assert outcome is not None
    assert outcome.action_type == "payment_link"
    assert outcome.observed_result == "failed"

def test_alt_method_payment_link_success_marks_payment_recovered(
    db_session,
    monkeypatch,
):
    payment = Payment(
        payment_id="pay_alt_method_success_123",
        amount=6000,
        status="failed",
    )

    action = Action(
        payment_id="pay_alt_method_success_123",
        action_type="alt_method",
        decision_type="auto",
    )

    audit = AuditLog(
        payment_id="pay_alt_method_success_123",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "payment_link",
                "payment_link_id": "plink_alt_success_123",
                "short_url": "https://rzp.io/rzp/alt123",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(action)
    db_session.add(audit)
    db_session.commit()

    def fake_payment_link_fetch(payment_link_id):
        assert payment_link_id == "plink_alt_success_123"
        return {
            "id": "plink_alt_success_123",
            "status": "paid",
        }

    monkeypatch.setattr(
        "app.services.execution.client.payment_link.fetch",
        fake_payment_link_fetch,
    )

    result = observe_outcome(
        db_session,
        payment,
    )

    db_session.refresh(payment)

    outcome = (
        db_session.query(Outcome)
        .filter(
            Outcome.payment_id == "pay_alt_method_success_123"
        )
        .first()
    )

    assert result["status"] == "recovered"
    assert payment.status == "recovered"
    assert outcome is not None
    assert outcome.action_type == "alt_method"
    assert outcome.observed_result == "success"