import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
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