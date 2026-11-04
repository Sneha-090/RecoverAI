import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.webhook_gateway import app


@pytest.mark.parametrize("method,path", [
    ("POST", "/create-order"), ("POST", "/process-payment"),
    ("POST", "/predict"), ("GET", "/latest-payment-for-order"),
    ("GET", "/checkout"), ("GET", "/checkout-config"),
    ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/.env"),
])
def test_public_gateway_cannot_reach_operator_routes_or_configuration(method, path):
    assert TestClient(app).request(method, path).status_code == 404


def test_gateway_rejects_unsigned_webhooks():
    assert TestClient(app).post("/webhooks/razorpay", json={"event": "connection_check"}).status_code == 400


def test_gateway_accepts_valid_signature_without_needing_operator_login():
    body = json.dumps({"event": "connection_check"}).encode()
    signature = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    response = TestClient(app).post(
        "/webhooks/razorpay", content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": signature},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
