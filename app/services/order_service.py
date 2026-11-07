from app.services.razorpay_client import client
from app.services.money import amount_paise
from app.services.payment_methods import alternate_methods


def create_test_order(amount_rupees: float, receipt: str, intent_id: str | None = None) -> dict:
    """
    Creates a Razorpay test-mode Order. Amount must be in paise.
    Returns the order dict, including 'id' (order_id) needed for checkout.
    """
    request = {
        "amount": amount_paise(amount_rupees),
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    }
    if intent_id:
        request["notes"] = {"recoverai_intent_id": intent_id}
    order = client.order.create(request)
    return order


def create_payment_link(amount_rupees: float, description: str, intent_id: str | None = None,
                        exclude_method: str | None = None) -> dict:
    """
    Creates a real Razorpay test-mode Payment Link. Used for the
    'payment_link' and 'alt_method' recovery actions.
    """
    request = {
        "amount": amount_paise(amount_rupees),
        "currency": "INR",
        "description": description,
        "accept_partial": False,
        "reminder_enable": False,
        "notify": {"sms": False, "email": False},
    }
    if intent_id:
        request["notes"] = {"recoverai_intent_id": intent_id}
    if exclude_method is not None:
        excluded, allowed = alternate_methods(exclude_method)
        request["options"] = {"checkout": {"method": {method: method in allowed
                                                    for method in (excluded, *allowed)}}}
        request.setdefault("notes", {})["recoverai_excluded_method"] = excluded
    link = client.payment_link.create(request)
    return link 
