"""Unit tests use dummy credentials and an in-memory default database."""

import os


# Set before test modules import Settings. Never inherit live provider keys.
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_unit"
os.environ["RAZORPAY_KEY_SECRET"] = "unit_test_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "unit_test_webhook"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
