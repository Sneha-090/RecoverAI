import hashlib
import hmac

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.webhooks import (
    verify_razorpay_signature,
    _find_recovery_case_by_order_id,
)
from app.db.session import Base
from app.models.models import AuditLog


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