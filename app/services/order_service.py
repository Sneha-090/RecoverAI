from app.services.razorpay_client import client


def create_test_order(amount_rupees: float, receipt: str, intent_id: str | None = None) -> dict:
    """
    Creates a Razorpay test-mode Order. Amount must be in paise.
    Returns the order dict, including 'id' (order_id) needed for checkout.
    """
    request = {
        "amount": int(amount_rupees * 100),
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    }
    if intent_id:
        request["notes"] = {"recoverai_intent_id": intent_id}
    order = client.order.create(request)
    return order


def create_payment_link(amount_rupees: float, description: str, intent_id: str | None = None) -> dict:
    """
    Creates a real Razorpay test-mode Payment Link. Used for the
    'payment_link' and 'alt_method' recovery actions.
    """
    request = {
        "amount": int(amount_rupees * 100),
        "currency": "INR",
        "description": description,
        "reminder_enable": True,
    }
    if intent_id:
        request["notes"] = {"recoverai_intent_id": intent_id}
    link = client.payment_link.create(request)
    return link 
