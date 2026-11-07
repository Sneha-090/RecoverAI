import pytest

from app.services.diagnosis import diagnose, FALLBACK_CAUSE
from app.models.models import Payment


@pytest.mark.parametrize('code', ['BAD_REQUEST_ERROR', 'GATEWAY_ERROR', 'SERVER_ERROR', None])
@pytest.mark.parametrize('reason', ['payment_failed', 'unseen_provider_reason', None])
def test_generic_codes_do_not_invent_a_bank_decline(code, reason):
    assert diagnose(Payment(razorpay_error_code=code, razorpay_error_reason=reason)) == FALLBACK_CAUSE


@pytest.mark.parametrize('reason,cause', [
    ('payment_declined', 'bank_declined'),
    ('card_declined', 'card_declined'),
    (' Insufficient_Funds ', 'insufficient_funds'),
    ('card_expired', 'expired_card'),
    ('expired_card', 'expired_card'),
    ('incorrect_card_details', 'invalid_card'),
    ('authentication_failed', 'authentication_failed'),
    ('gateway_technical_error', 'network_error'),
    ('issuer_technical_error', 'network_error'),
    ('payment_cancelled', 'customer_cancelled'),
])
def test_specific_reason_takes_precedence_over_broad_error_code(reason, cause):
    payment = Payment(razorpay_error_code='BAD_REQUEST_ERROR', razorpay_error_reason=reason)
    assert diagnose(payment) == cause
