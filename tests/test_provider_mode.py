from unittest.mock import Mock
import pytest
from app.config import settings
from app.services.order_service import create_test_order,create_payment_link
from app.services.razorpay_client import BoundedProviderSession,ProviderModeError


@pytest.mark.parametrize('kind',['order','payment_link'])
@pytest.mark.parametrize('key',['rzp_live_example','','invalid'])
def test_creation_rejects_non_test_keys_before_sdk_call(monkeypatch,kind,key):
    monkeypatch.setattr(settings,'razorpay_key_id',key)
    provider=Mock(side_effect=AssertionError('No provider call allowed'))
    monkeypatch.setattr('app.services.order_service.client.order.create',provider)
    monkeypatch.setattr('app.services.order_service.client.payment_link.create',provider)
    with pytest.raises(ProviderModeError):
        if kind=='order':create_test_order(499,'fixture')
        else:create_payment_link(499,'fixture')
    provider.assert_not_called()


@pytest.mark.parametrize('method',['GET','POST','PATCH','DELETE'])
@pytest.mark.parametrize('auth',[('rzp_live_example','private'),None,(),('rzp_test_fixture',)])
def test_transport_rejects_non_test_auth_even_with_test_settings(monkeypatch,method,auth):
    underlying=Mock(side_effect=AssertionError('Network must not be called'))
    monkeypatch.setattr('requests.Session.request',underlying)
    with pytest.raises(ProviderModeError):
        BoundedProviderSession().request(method,'https://api.razorpay.com/v1/orders',auth=auth)
    underlying.assert_not_called()


def test_transport_rechecks_configuration_before_sending_cached_sdk_auth(monkeypatch):
    monkeypatch.setattr(settings,'razorpay_key_id','rzp_live_changed')
    underlying=Mock();monkeypatch.setattr('requests.Session.request',underlying)
    with pytest.raises(ProviderModeError):
        BoundedProviderSession().request('POST','https://api.razorpay.com/v1/orders',auth=('rzp_test_cached','private'))
    underlying.assert_not_called()



@pytest.mark.parametrize('error_type', ['ConnectionError', 'ReadTimeout'])
def test_provider_get_retries_one_connection_failure(monkeypatch,error_type):
    import requests
    error=getattr(requests.exceptions,error_type)('private connection detail')
    response=Mock()
    send=Mock(side_effect=[error,response])
    monkeypatch.setattr('requests.Session.request',send)
    result=BoundedProviderSession().request('GET','https://api.razorpay.com/v1/orders/order_test',auth=('rzp_test_fixture','private'))
    assert result is response and send.call_count==2
    assert all(call.kwargs['timeout']==(5,20) for call in send.call_args_list)


def test_provider_get_stops_after_two_failed_reads(monkeypatch):
    import requests
    from app.services.razorpay_client import ProviderReadUnavailable
    send=Mock(side_effect=requests.ConnectionError('PRIVATE_NETWORK_DETAIL'))
    monkeypatch.setattr('requests.Session.request',send)
    with pytest.raises(ProviderReadUnavailable) as caught:
        BoundedProviderSession().request('GET','https://api.razorpay.com/v1/orders/order_test',auth=('rzp_test_fixture','private'))
    assert send.call_count==2 and 'PRIVATE_NETWORK_DETAIL' not in str(caught.value)


@pytest.mark.parametrize('method',['POST','PATCH','DELETE','PUT'])
@pytest.mark.parametrize('error_type',['ConnectionError','ReadTimeout'])
def test_provider_write_is_never_retried_on_network_failure(monkeypatch,method,error_type):
    import requests
    error=getattr(requests.exceptions,error_type)
    send=Mock(side_effect=error('uncertain write'))
    monkeypatch.setattr('requests.Session.request',send)
    with pytest.raises(error):
        BoundedProviderSession().request(method,'https://api.razorpay.com/v1/orders',auth=('rzp_test_fixture','private'))
    assert send.call_count==1
