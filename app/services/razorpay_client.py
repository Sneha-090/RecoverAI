import razorpay

from app.config import settings

client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
def fetch_payment(payment_id: str):
    return client.payment.fetch(payment_id)