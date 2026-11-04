from unittest.mock import Mock

import pytest

from app.services import order_service


@pytest.mark.parametrize("kind", ["order", "payment_link"])
@pytest.mark.parametrize("intent_id", [None, "durable-intent"])
def test_provider_notes_identify_recovery_intent_without_changing_plain_checkout(monkeypatch, kind, intent_id):
    provider = Mock(return_value={"id": "provider_resource"})
    if kind == "order":
        monkeypatch.setattr(order_service.client.order, "create", provider)
        result = order_service.create_test_order(499, "test_receipt", intent_id=intent_id)
    else:
        monkeypatch.setattr(order_service.client.payment_link, "create", provider)
        result = order_service.create_payment_link(499, "Test recovery", intent_id=intent_id)
    request = provider.call_args.args[0]
    assert request["amount"] == 49900
    assert request["currency"] == "INR"
    assert result["id"] == "provider_resource"
    if intent_id:
        assert request["notes"] == {"recoverai_intent_id": intent_id}
    else:
        assert "notes" not in request
