import hashlib
import hmac
import json

import pytest
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