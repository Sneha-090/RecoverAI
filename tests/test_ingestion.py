import pytest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.config import settings
from app.models.models import Payment
from app.services.eligibility import is_recovery_eligible
from app.services.ingestion import fetch_and_store_payment


@pytest.fixture
def db_session():
    # Temporary in-memory database.
    # Real recoverai.db is not touched.
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


class FakePaymentAPI:
    def fetch(self, payment_id):
        return {
            "id": payment_id,
            "order_id": "order_test_123",
            "amount": 49900,
            "method": "card",
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "status": "failed",
        }


class FakeClient:
    payment = FakePaymentAPI()


def test_error_reason_is_stored_in_payment(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.client",
        FakeClient(),
    )

    payment = fetch_and_store_payment(
        db_session,
        "pay_test_123",
    )

    assert payment.razorpay_error_code == "BAD_REQUEST_ERROR"
    assert payment.razorpay_error_reason == "insufficient_funds"
    assert payment.status == "failed"
    assert payment.razorpay_state == "failed"
    assert payment.order_id == "order_test_123"
    assert payment.amount == 499.0


@pytest.mark.parametrize("status", ["recovered", "closed_unrecovered"])
def test_refetch_preserves_terminal_recovery_status(db_session, monkeypatch, status):
    payment = Payment(payment_id="pay_terminal", amount=499, status=status)
    db_session.add(payment)
    db_session.commit()
    monkeypatch.setattr("app.services.ingestion.client", FakeClient())

    result = fetch_and_store_payment(db_session, payment.payment_id)

    assert result.status == status
    assert result.razorpay_state == "failed"
    assert is_recovery_eligible(result)[0] is False


@pytest.mark.parametrize("already_ingested", [False, True])
def test_old_provider_payment_does_not_get_a_fresh_recovery_window(
    db_session, monkeypatch, already_ingested,
):
    created_at = datetime.utcnow() - timedelta(days=settings.max_recovery_window_days + 1)
    timestamp = int((created_at - datetime(1970, 1, 1)).total_seconds())
    if already_ingested:
        db_session.add(Payment(payment_id="pay_old", amount=499, status="failed"))
        db_session.commit()
    payload = FakePaymentAPI().fetch("pay_old")
    payload["created_at"] = timestamp
    monkeypatch.setattr("app.services.ingestion.client.payment.fetch", lambda payment_id: payload)

    payment = fetch_and_store_payment(db_session, "pay_old")

    assert payment.created_at == datetime.utcfromtimestamp(timestamp)
    assert is_recovery_eligible(payment)[0] is False
