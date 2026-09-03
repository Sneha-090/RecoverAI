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

    from app.models.models import Action, Payment, Outcome


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