import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.webhooks import (
    verify_razorpay_signature,
    _find_recovery_case_by_order_id,
    _find_recovery_case_by_payment_link_description,
)
from app.db.session import Base
from app.models.models import AuditLog, Payment
from app.main import app


@pytest.fixture
def db_session():
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


def test_valid_razorpay_signature():
    body = b'{"event":"payment.failed"}'
    secret = "test_webhook_secret"

    import app.api.webhooks as webhooks

    original_secret = webhooks.settings.razorpay_webhook_secret
    webhooks.settings.razorpay_webhook_secret = secret

    try:
        signature = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        assert verify_razorpay_signature(body, signature) is True
    finally:
        webhooks.settings.razorpay_webhook_secret = original_secret


def test_invalid_razorpay_signature():
    body = b'{"event":"payment.failed"}'
    secret = "test_webhook_secret"

    import app.api.webhooks as webhooks

    original_secret = webhooks.settings.razorpay_webhook_secret
    webhooks.settings.razorpay_webhook_secret = secret

    try:
        assert verify_razorpay_signature(
            body,
            "this_is_not_a_valid_signature",
        ) is False
    finally:
        webhooks.settings.razorpay_webhook_secret = original_secret


def test_find_recovery_case_by_order_id(db_session):
    audit = AuditLog(
        payment_id="pay_original_123",
        event_type="executed",
        payload_json='{"type":"order","order_id":"order_recovery_123"}',
    )

    db_session.add(audit)
    db_session.commit()

    result = _find_recovery_case_by_order_id(
        db_session,
        "order_recovery_123",
    )

    assert result == "pay_original_123"


def test_find_recovery_case_ignores_unrelated_order(db_session):
    audit = AuditLog(
        payment_id="pay_original_123",
        event_type="executed",
        payload_json='{"type":"order","order_id":"order_recovery_123"}',
    )

    db_session.add(audit)
    db_session.commit()

    result = _find_recovery_case_by_order_id(
        db_session,
        "some_other_order_999",
    )

    assert result is None


def test_find_recovery_case_by_human_approved_order(db_session):
    audit = AuditLog(
        payment_id="pay_human_789",
        event_type="human_approved_executed",
        payload_json='{"type":"order","order_id":"order_human_789"}',
    )

    db_session.add(audit)
    db_session.commit()

    result = _find_recovery_case_by_order_id(
        db_session,
        "order_human_789",
    )

    assert result == "pay_human_789"


def test_find_recovery_case_by_payment_link_description(db_session):
    audit = AuditLog(
        payment_id="pay_payment_link_123",
        event_type="executed",
        payload_json=(
            '{"type":"payment_link",'
            '"payment_link_id":"plink_TWkIhRTWeOG10I",'
            '"short_url":"https://rzp.io/rzp/test123"}'
        ),
    )

    db_session.add(audit)
    db_session.commit()

    result = _find_recovery_case_by_payment_link_description(
        db_session,
        "#TWkIhRTWeOG10I",
    )

    assert result == "pay_payment_link_123"


def test_failed_recovery_order_can_be_linked_to_original_case(db_session):
    payment = Payment(
        payment_id="pay_original_456",
        order_id="order_original_456",
        amount=5000,
        status="failed",
    )

    recovery_audit = AuditLog(
        payment_id="pay_original_456",
        event_type="executed",
        payload_json=json.dumps(
            {
                "type": "order",
                "order_id": "order_recovery_456",
            }
        ),
    )

    db_session.add(payment)
    db_session.add(recovery_audit)
    db_session.commit()

    original_payment_id = _find_recovery_case_by_order_id(
        db_session,
        "order_recovery_456",
    )

    assert original_payment_id == "pay_original_456"
def test_duplicate_webhook_event_is_detected(db_session):
    from app.api.webhooks import (
        _webhook_event_already_processed,
        _record_processed_webhook,
    )

    event_id = "evt_test_duplicate_123"

    # First time: event should not exist.
    assert _webhook_event_already_processed(
        db_session,
        event_id,
    ) is False

    # Record the event as processed.
    _record_processed_webhook(
        db=db_session,
        payment_id="pay_test_123",
        event_type="payment.failed",
        razorpay_event_id=event_id,
        payload={
            "event": "payment.failed",
            "test": True,
        },
    )

    # Second time: same event ID must be detected.
    assert _webhook_event_already_processed(
        db_session,
        event_id,
    ) is True

@pytest.fixture
def client(db_session, monkeypatch):
    import app.api.webhooks as webhooks

    monkeypatch.setattr(
        webhooks,
        "SessionLocal",
        lambda: db_session,
    )

    return TestClient(app)

def test_webhook_endpoint_rejects_duplicate_event(
    client,
    db_session,
    monkeypatch,
):
    import app.api.webhooks as webhooks

    secret = "test_webhook_secret"

    original_secret = webhooks.settings.razorpay_webhook_secret
    webhooks.settings.razorpay_webhook_secret = secret

    try:
        payload = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_duplicate_123",
                        "order_id": None,
                    }
                }
            },
        }

        body = json.dumps(payload).encode("utf-8")

        signature = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        event_id = "evt_duplicate_123"

        # Keep the first request focused on idempotency.
        # We do not want diagnosis/execution/Razorpay calls in this test.
        payment = Payment(
            payment_id="pay_duplicate_123",
            amount=5000,
            status="failed",
        )

        db_session.add(payment)
        db_session.commit()

        monkeypatch.setattr(
            webhooks,
            "fetch_and_store_payment",
            lambda db, payment_id: payment,
        )

        monkeypatch.setattr(
            webhooks,
            "diagnose_and_store",
            lambda db, payment: type(
                "DiagnosisResult",
                (),
                {"cause": "test_failure"},
            )(),
        )

        monkeypatch.setattr(
            webhooks,
            "execute_action",
            lambda db, payment: {
                "chosen_action": "retry",
                "decision_type": "auto",
                "executed": True,
            },
        )

        # First request: should be processed.
        first_response = client.post(
            "/webhooks/razorpay",
            content=body,
            headers={
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": event_id,
            },
        )

        assert first_response.status_code == 200
        assert first_response.json()["status"] == "processed"

        # Second request with the exact same Razorpay event ID.
        second_response = client.post(
            "/webhooks/razorpay",
            content=body,
            headers={
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": event_id,
            },
        )

        assert second_response.status_code == 200
        assert second_response.json()["status"] == "already_processed"
        assert second_response.json()["razorpay_event_id"] == event_id

    finally:
        webhooks.settings.razorpay_webhook_secret = original_secret