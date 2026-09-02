from app.services.diagnosis import diagnose, FALLBACK_CAUSE
from app.models.models import Payment


def make_payment(error_code=None, error_reason=None):
    return Payment(
        payment_id="pay_test",
        amount=499,
        razorpay_error_code=error_code,
        razorpay_error_reason=error_reason,
    )


def test_known_error_reason_maps_correctly():
    p = make_payment(error_code="BAD_REQUEST_ERROR", error_reason="insufficient_funds")
    assert diagnose(p) == "insufficient_funds"


def test_falls_back_to_error_code_when_reason_unknown():
    p = make_payment(error_code="GATEWAY_ERROR", error_reason=None)
    assert diagnose(p) == "bank_declined"


def test_unmapped_code_uses_fallback_never_null():
    p = make_payment(error_code="SOME_UNSEEN_CODE", error_reason=None)
    assert diagnose(p) == FALLBACK_CAUSE
    assert diagnose(p) is not None


def test_real_day1_payment_case():
    p = make_payment(error_code="BAD_REQUEST_ERROR", error_reason="payment_failed")
    assert diagnose(p) == "bank_declined"







