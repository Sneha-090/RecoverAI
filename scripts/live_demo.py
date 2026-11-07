"""Legacy entry point: now defaults to the isolated offline walkthrough.

For actual Razorpay Test Mode checkout use the authenticated application and
TEST_MODE_VERIFICATION.md; this command never creates real provider resources.
"""
from scripts.offline_demo import main

if __name__ == '__main__':
    main()
