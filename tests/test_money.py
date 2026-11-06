from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.services.money import amount_paise
from app.services import order_service


@pytest.mark.parametrize('amount,expected', [(19.9, 1990), (0.29, 29), (4.01, 401),
    (Decimal('19.90'), 1990), ('19.90', 1990), (499, 49900), ('1.230', 123), ('0.01', 1)])
def test_exact_conversion(amount, expected):
    assert amount_paise(amount) == expected


@pytest.mark.parametrize('amount', [0, -1, '19.901', float('nan'), float('inf'), None, True, 'invalid'])
def test_invalid_amount_is_rejected(amount):
    with pytest.raises(ValueError, match='whole paise'):
        amount_paise(amount)


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
@pytest.mark.parametrize('amount,expected', [(19.9, 1990), (0.29, 29), (4.01, 401)])
def test_provider_receives_exact_integer_paise(monkeypatch, kind, amount, expected):
    provider = Mock(return_value={'id': 'provider_resource'})
    monkeypatch.setattr(order_service.client.order if kind == 'order' else order_service.client.payment_link, 'create', provider)
    if kind == 'order':
        order_service.create_test_order(amount, 'test_receipt')
    else:
        order_service.create_payment_link(amount, 'Test recovery')
    assert provider.call_args.args[0]['amount'] == expected
    assert isinstance(provider.call_args.args[0]['amount'], int)


@pytest.mark.parametrize('kind', ['order', 'payment_link'])
def test_fractional_paise_never_reaches_provider(monkeypatch, kind):
    provider = Mock(side_effect=AssertionError('Invalid amount must not reach provider'))
    monkeypatch.setattr(order_service.client.order if kind == 'order' else order_service.client.payment_link, 'create', provider)
    with pytest.raises(ValueError):
        if kind == 'order':
            order_service.create_test_order(19.901, 'test_receipt')
        else:
            order_service.create_payment_link(19.901, 'Test recovery')
    provider.assert_not_called()
