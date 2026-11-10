import razorpay
import requests

from app.config import settings

class ProviderModeError(ValueError):
    pass


def require_test_mode():
    if not settings.razorpay_key_id.startswith('rzp_test_'):
        raise ProviderModeError('RecoverAI currently permits Razorpay Test Mode only')


class ProviderReadUnavailable(RuntimeError):
    """A bounded read failed; no provider mutation is retried by this transport."""


class BoundedProviderSession(requests.Session):
    def request(self, method, url, **kwargs):
        from urllib.parse import urlparse
        auth = kwargs.get('auth')
        if auth is not None or urlparse(url).hostname == 'api.razorpay.com':
            require_test_mode()
            if not isinstance(auth, tuple) or len(auth) != 2 or not isinstance(auth[0], str) or not auth[0].startswith('rzp_test_'):
                raise ProviderModeError('Provider request requires Test Mode authentication')
        kwargs.setdefault('timeout', (5,20))
        is_read = method.upper() == 'GET'
        for attempt in range(2 if is_read else 1):
            try:
                return super().request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as error:
                if not is_read:
                    raise
                if attempt == 1:
                    raise ProviderReadUnavailable('Provider read temporarily unavailable') from error


client = razorpay.Client(session=BoundedProviderSession(),
                         auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
def fetch_payment(payment_id: str):
    return client.payment.fetch(payment_id)