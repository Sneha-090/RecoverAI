from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.main import app
from app.services.passwords import hash_password


PASSWORD = "local-test-password-123"


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setattr(settings, "operator_username", "operator")
    monkeypatch.setattr(settings, "operator_password_hash", SecretStr(hash_password(PASSWORD)))
    return ("operator", PASSWORD)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path,method,body", [
    ("/create-order", "POST", {"amount": "499.00"}),
    ("/process-payment", "POST", {"payment_id": "pay_test123"}),
    ("/predict", "POST", {}),
    ("/latest-payment-for-order?order_id=order_test123", "GET", None),
    ("/checkout", "GET", None),
    ("/checkout-config?order_id=order_test123", "GET", None),
])
def test_operator_routes_reject_anonymous_access(client, operator, path, method, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert "Basic" in response.headers["www-authenticate"]


def test_missing_auth_configuration_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_username", "")
    monkeypatch.setattr(settings, "operator_password_hash", SecretStr(""))
    assert client.post("/create-order", json={"amount": "499"}).status_code == 503


def test_wrong_password_never_calls_provider(client, operator, monkeypatch):
    provider = Mock(side_effect=AssertionError("Unauthorized provider call"))
    monkeypatch.setattr("app.main.create_test_order", provider)
    assert client.post("/create-order", json={"amount": "499"}, auth=("operator", "wrong")).status_code == 401
    provider.assert_not_called()


@pytest.mark.parametrize("amount", ["0", "-1", "0.001", "10000000.01", "NaN", "Infinity", "abc"])
def test_invalid_order_amount_is_rejected_before_provider(client, operator, monkeypatch, amount):
    provider = Mock(side_effect=AssertionError("Invalid amount reached provider"))
    monkeypatch.setattr("app.main.create_test_order", provider)
    assert client.post("/create-order", json={"amount": amount}, auth=operator).status_code == 422
    provider.assert_not_called()


def test_valid_order_preserves_exact_paise(client, operator, monkeypatch):
    provider = Mock(return_value={"id": "order_test123", "amount": 29})
    monkeypatch.setattr("app.services.order_service.client.order.create", provider)
    response = client.post("/create-order", json={"amount": "0.29"}, auth=operator)
    assert response.status_code == 200
    assert response.json()["amount_paise"] == 29
    assert provider.call_args.args[0]["amount"] == 29


@pytest.mark.parametrize("path", ["/create-order?amount=499", "/process-payment?payment_id=pay_test123"])
def test_get_cannot_trigger_payment_changes(client, path):
    assert client.get(path).status_code == 405


def test_invalid_payment_id_is_rejected(client, operator, monkeypatch):
    fetch = Mock(side_effect=AssertionError("Invalid ID reached provider"))
    monkeypatch.setattr("app.main.fetch_and_store_payment", fetch)
    assert client.post("/process-payment", json={"payment_id": "../../secret"}, auth=operator).status_code == 422
    fetch.assert_not_called()


def test_authenticated_post_processes_requested_payment_and_closes_session(client, operator, monkeypatch):
    db = Mock()
    payment = SimpleNamespace(
        payment_id="pay_test123", amount=499, status="failed",
        razorpay_error_code="SERVER_ERROR", razorpay_error_reason="processing_error",
    )
    fetch = Mock(return_value=payment)
    monkeypatch.setattr("app.main.SessionLocal", lambda: db)
    monkeypatch.setattr("app.main.fetch_and_store_payment", fetch)
    monkeypatch.setattr("app.main.diagnose_and_store", lambda *_: SimpleNamespace(cause="network_error"))
    monkeypatch.setattr("app.main.execute_action", lambda *_: {
        "chosen_action": "retry", "decision_type": "auto", "reason": "test reason",
        "executed": True, "razorpay_payload": {"order_id": "order_test123"},
    })
    response = client.post("/process-payment", json={"payment_id": "pay_test123"}, auth=operator)
    assert response.status_code == 200
    assert response.json()["payment_id"] == "pay_test123"
    assert response.json()["executed"] is True
    fetch.assert_called_once_with(db, "pay_test123")
    db.close.assert_called_once()


def test_checkout_uses_provider_amount_and_only_exposes_public_key(client, operator, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base
    from sqlalchemy.pool import StaticPool
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr('app.main.SessionLocal',sessionmaker(bind=engine))
    monkeypatch.setattr("app.services.razorpay_client.client.order.fetch", lambda _: {
        "id": "order_test123", "amount": 49900, "currency": "INR",
        "status":"created","amount_paid":0,"amount_due":49900,"attempts":0,
    })
    response = client.get("/checkout-config?order_id=order_test123&amount=1", auth=operator)
    assert response.status_code == 200
    assert response.json() == {
        "key_id": settings.razorpay_key_id, "order_id": "order_test123",
        "amount_paise": 49900, "currency": "INR",
        "checkout_note": "A fresh checkout requires an explicit payment by the customer; no automatic debit is performed.",
    }
    page = client.get("/checkout", auth=operator)
    assert page.status_code == 200
    assert settings.operator_password_hash.get_secret_value() not in page.text
    assert "rzp_test_TU2MpmBcUHatw7" not in page.text


def test_untrusted_origin_is_not_allowed(client, operator):
    response = client.options("/create-order", headers={
        "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cross_origin_mutation_is_blocked_even_with_browser_credentials(client, operator, monkeypatch):
    provider = Mock(side_effect=AssertionError("Untrusted browser origin reached provider"))
    monkeypatch.setattr("app.main.create_test_order", provider)
    response = client.post("/create-order", json={"amount": "499"}, auth=operator,
                           headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    provider.assert_not_called()


def test_health_is_available_without_login(client):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("field,value", [("past_rate", 1.5), ("attempts", -1), ("action_type", "charge_everyone"), ("cause", "unknown")])
def test_prediction_inputs_are_bounded(client, operator, field, value):
    payload = {"amount": 499, "cause": "network_error", "attempts": 0,
               "days_since_failure": 1, "past_rate": 0.5, "action_type": "retry"}
    payload[field] = value
    assert client.post("/predict", json=payload, auth=operator).status_code == 422



def test_untrained_prediction_returns_actionable_validation_error(client, operator):
    response = client.post('/predict', auth=operator, json={
        'amount':499,'cause':'expired_card','attempts':0,'days_since_failure':0,
        'past_rate':.5,'action_type':'payment_link'})
    assert response.status_code == 422
    assert 'manual assessment' in response.json()['detail']



def test_checkout_provider_read_failure_returns_sanitized_service_unavailable(client,operator,monkeypatch):
    from app.services.razorpay_client import ProviderReadUnavailable
    monkeypatch.setattr('app.services.operator_checkout.client.order.fetch',Mock(side_effect=ProviderReadUnavailable('PRIVATE_RESPONSE')))
    response=client.get('/checkout-config?order_id=order_readFailure',auth=operator)
    assert response.status_code==503 and response.headers['retry-after']=='30'
    assert 'PRIVATE_RESPONSE' not in response.text and 'Provider lookup temporarily unavailable' in response.text
