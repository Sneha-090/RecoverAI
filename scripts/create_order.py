import sys

from app.services.order_service import create_test_order


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.create_order <amount_in_rupees>")
        sys.exit(1)

    try:
        amount_rupees = float(sys.argv[1])
    except ValueError:
        print("Amount must be a number.")
        sys.exit(1)

    order = create_test_order(
        amount_rupees=amount_rupees,
        receipt=f"recoverai_test_{int(amount_rupees)}",
    )

    print("Order created:")
    print("order_id:", order["id"])
    print("amount (paise):", order["amount"])