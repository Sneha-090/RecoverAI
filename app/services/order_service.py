from app.services.razorpay_client import client


def create_test_order(amount_rupees: float, receipt: str) -> dict:
    """
    Creates a Razorpay test-mode Order. Amount must be in paise.
    Returns the order dict, including 'id' (order_id) needed for checkout.
    """
    order = client.order.create({
        "amount": int(amount_rupees * 100),
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    })
    return order


def create_payment_link(amount_rupees: float, description: str) -> dict:
    """
    Creates a real Razorpay test-mode Payment Link. Used for the
    'payment_link' and 'alt_method' recovery actions.
    """
    link = client.payment_link.create({
        "amount": int(amount_rupees * 100),
        "currency": "INR",
        "description": description,
        "reminder_enable": True,
    })
    return link