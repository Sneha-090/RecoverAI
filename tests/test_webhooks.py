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


def signed_event(event_id=None):
    from app.config import settings
    body = json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_claim_test"}}},
    }).encode()
    headers = {"X-Razorpay-Signature": hmac.new(
        settings.razorpay_webhook_secret.encode(), body, hashlib.sha256,
    ).hexdigest()}
    if event_id is not None:
        headers["X-Razorpay-Event-Id"] = event_id
    return body, headers


@pytest.mark.parametrize("kind,event", [("order", "payment.captured"),
                                        ("payment_link", "payment.captured"),
                                        ("payment_link", "payment.failed")])
def test_signed_historical_resource_event_uses_original_case(client, db_session, monkeypatch, kind, event):
    from datetime import datetime, timedelta
    from unittest.mock import Mock
    from app.config import settings
    from app.models.models import Action, Outcome, ExecutionOutcome, RecoveryReservation
    from app.services.execution_records import record_execution
    payment = Payment(payment_id="pay_history", amount=499, status="failed")
    db_session.add(payment)
    executions = []
    for offset, resource_kind, resource_id in [(2, kind, "old"), (1, "payment_link", "new")]:
        when = datetime.utcnow() - timedelta(hours=offset)
        action = Action(payment_id=payment.payment_id,
                        action_type="retry" if resource_kind == "order" else "payment_link",
                        decision_type="auto", chosen_at=when)
        provider_id = ("order_" if resource_kind == "order" else "plink_") + resource_id
        payload = {"type": resource_kind,
                   "order_id" if resource_kind == "order" else "payment_link_id": provider_id}
        audit = AuditLog(payment_id=payment.payment_id, event_type="executed",
                         timestamp=when + timedelta(seconds=1), payload_json=json.dumps(payload))
        db_session.add_all([action, audit])
        db_session.flush()
        executions.append(record_execution(db_session, payment, action, audit, payload))
    old_id, current_id = [row.id for row in executions]
    db_session.add(RecoveryReservation(payment_id=payment.payment_id, owner="waiting", state="awaiting_outcome"))
    db_session.commit()
    monkeypatch.setattr("app.services.execution.client.order.payments", lambda _: {
        "items": [{"status": "captured", "amount": 49900, "currency": "INR"}]})
    monkeypatch.setattr("app.services.execution.client.payment_link.fetch", lambda _: {
        "id": "plink_old", "status": "paid" if event == "payment.captured" else "created",
        "amount": 49900, "amount_paid": 49900, "currency": "INR"})
    ingest = Mock(side_effect=AssertionError("A recovery payment must not become a separate case"))
    monkeypatch.setattr("app.api.webhooks.fetch_and_store_payment", ingest)
    advance = Mock(side_effect=AssertionError("A historical event must not create another action"))
    monkeypatch.setattr("app.services.execution._execute_action", advance)
    entity = {"id": "pay_provider", "order_id": "order_old" if kind == "order" else "order_link",
              "description": "#old" if kind == "payment_link" else None}
    body = json.dumps({"event": event, "payload": {"payment": {"entity": entity}}}).encode()
    headers = {"X-Razorpay-Event-Id": "evt_historical", "X-Razorpay-Signature": hmac.new(
        settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()}
    response = client.post("/webhooks/razorpay", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["outcome"]["status"] == ("recovered" if event == "payment.captured" else "awaiting_outcome")
    assert client.post("/webhooks/razorpay", content=body, headers=headers).json()["status"] == "already_processed"
    # Different provider event ID for the same capture must still not duplicate the outcome.
    headers["X-Razorpay-Event-Id"] = "evt_historical_redelivery"
    assert client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 200
    assert db_session.query(Payment).count() == 1
    assert db_session.query(Outcome).count() == (1 if event == "payment.captured" else 0)
    assert db_session.get(ExecutionOutcome, current_id) is None
    if event == "payment.captured":
        assert db_session.get(ExecutionOutcome, old_id) is not None
    ingest.assert_not_called()
    advance.assert_not_called()


def test_handled_webhook_requires_event_id(client, monkeypatch):
    from unittest.mock import Mock
    fetch = Mock(side_effect=AssertionError("Must reject before ingestion"))
    monkeypatch.setattr("app.api.webhooks.fetch_and_store_payment", fetch)
    body, headers = signed_event()
    assert client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 400
    fetch.assert_not_called()


@pytest.mark.parametrize("state", ["processing", "needs_reconciliation", "processed"])
def test_reserved_event_never_reexecutes(client, db_session, monkeypatch, state):
    from unittest.mock import Mock
    from app.models.models import WebhookReceipt
    db_session.add(WebhookReceipt(event_id="evt_reserved", state=state))
    db_session.commit()
    fetch = Mock(side_effect=AssertionError("Must not ingest duplicate"))
    monkeypatch.setattr("app.api.webhooks.fetch_and_store_payment", fetch)
    body, headers = signed_event("evt_reserved")
    response = client.post("/webhooks/razorpay", content=body, headers=headers)
    assert response.status_code == (200 if state == "processed" else 503)
    fetch.assert_not_called()


def test_interrupted_webhook_is_not_blindly_replayed(client, db_session, monkeypatch):
    from unittest.mock import Mock
    from app.models.models import WebhookReceipt
    fetch = Mock(side_effect=TimeoutError("interrupted request"))
    monkeypatch.setattr("app.api.webhooks.fetch_and_store_payment", fetch)
    body, headers = signed_event("evt_interrupted")
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        assert safe_client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 500
        assert safe_client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 503
    assert db_session.get(WebhookReceipt, "evt_interrupted").state == "needs_reconciliation"
    assert fetch.call_count == 1


def test_busy_outcome_event_can_retry_after_other_request_finishes(client, db_session, monkeypatch):
    from unittest.mock import Mock
    from app.config import settings
    from app.models.models import WebhookReceipt
    from app.services.reservations import RecoveryInProgress
    db_session.add(Payment(payment_id="pay_original", amount=1000, status="failed"))
    db_session.add(AuditLog(
        payment_id="pay_original", event_type="executed",
        payload_json=json.dumps({"type": "order", "order_id": "order_recovery"}),
    ))
    db_session.commit()
    observe = Mock(side_effect=[RecoveryInProgress("busy"), {"status": "recovered"}])
    monkeypatch.setattr("app.api.webhooks.observe_outcome", observe)
    body = json.dumps({
        "event": "payment.captured", "payload": {"payment": {"entity": {
            "id": "pay_recovery", "order_id": "order_recovery",
        }}},
    }).encode()
    headers = {
        "X-Razorpay-Event-Id": "evt_busy_capture",
        "X-Razorpay-Signature": hmac.new(
            settings.razorpay_webhook_secret.encode(), body, hashlib.sha256,
        ).hexdigest(),
    }
    assert client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 503
    assert db_session.get(WebhookReceipt, "evt_busy_capture").state == "retryable"
    assert client.post("/webhooks/razorpay", content=body, headers=headers).status_code == 200
    assert db_session.get(WebhookReceipt, "evt_busy_capture").state == "processed"
    assert observe.call_count == 2


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
