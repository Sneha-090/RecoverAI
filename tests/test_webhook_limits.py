import hashlib,hmac,json
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.api.webhooks import MAX_WEBHOOK_BODY_BYTES,verify_razorpay_signature
from app.webhook_gateway import app


def signature(body):return hmac.new(settings.razorpay_webhook_secret.encode(),body,hashlib.sha256).hexdigest()


@pytest.mark.parametrize('chunked',[False,True])
def test_oversize_webhook_is_rejected_before_database_or_provider(monkeypatch,chunked):
    db=Mock(side_effect=AssertionError('Oversize input must not reach storage'))
    monkeypatch.setattr('app.api.webhooks.SessionLocal',db)
    body=b'x'*(MAX_WEBHOOK_BODY_BYTES+1)
    content=(part for part in [body[:MAX_WEBHOOK_BODY_BYTES],body[MAX_WEBHOOK_BODY_BYTES:]]) if chunked else body
    with TestClient(app) as transport:
        result=transport.post('/webhooks/razorpay',content=content,headers={'X-Razorpay-Signature':'0'*64})
    assert result.status_code==413
    db.assert_not_called()


def test_signature_uses_exact_bounded_raw_bytes_at_limit():
    body=json.dumps({'event':'connection_check','padding':''},separators=(',',':')).encode()
    body=body.replace(b'"padding":""',b'"padding":"'+b'x'*(MAX_WEBHOOK_BODY_BYTES-len(body))+b'"')
    assert len(body)==MAX_WEBHOOK_BODY_BYTES
    with TestClient(app) as transport:
        response=transport.post('/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signature(body)})
    assert response.status_code==200 and response.json()['status']=='ignored'


def test_deep_signed_json_is_rejected_without_server_exception():
    body=b'['*2000+b'0'+b']'*2000
    with TestClient(app) as transport:
        result=transport.post('/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':signature(body)})
    assert result.status_code==400


@pytest.mark.parametrize('value',['é'*64,'0'*65,'0'*63,None])
def test_malformed_signature_fails_closed(value):
    assert not verify_razorpay_signature(b'{}',value)


def test_unconfigured_webhook_secret_is_never_treated_as_valid(monkeypatch):
    monkeypatch.setattr(settings,'razorpay_webhook_secret','')
    body=b'{}'
    assert not verify_razorpay_signature(body,hmac.new(b'',body,hashlib.sha256).hexdigest())
