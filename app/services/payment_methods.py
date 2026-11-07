"""Documented Payment Link checkout methods; unknown inputs must not pretend to switch."""

CHECKOUT_METHODS = ('card', 'upi', 'netbanking', 'wallet')


def alternate_methods(failed_method):
    method = (failed_method or '').strip().lower()
    if method not in CHECKOUT_METHODS:
        raise ValueError('A supported original payment method is required for alternate-method recovery')
    return method, [item for item in CHECKOUT_METHODS if item != method]


def is_alt_method_eligible(payment):
    try:
        alternate_methods(payment.payment_method)
    except ValueError as error:
        return False, str(error)
    return True, 'alternate checkout hides the original failed method'
