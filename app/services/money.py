"""Exact INR conversion shared by provider requests and execution records."""

from decimal import Decimal, DecimalException, localcontext


def amount_paise(amount):
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value <= 0:
            raise ValueError
        with localcontext() as context:
            context.prec = max(28, len(value.as_tuple().digits) + 2)
            paise = value * 100
            if paise != paise.to_integral_value():
                raise ValueError
            return int(paise)
    except (DecimalException, ValueError, TypeError, OverflowError):
        raise ValueError('Amount must be positive, finite and expressed in whole paise.') from None
