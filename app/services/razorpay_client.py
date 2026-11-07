import razorpay
import requests

from app.config import settings

class BoundedProviderSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', (5,20))
        return super().request(method,url,**kwargs)


client = razorpay.Client(session=BoundedProviderSession(),
                         auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
def fetch_payment(payment_id: str):
    return client.payment.fetch(payment_id)