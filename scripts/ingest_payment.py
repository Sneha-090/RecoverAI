from app.db.session import SessionLocal
from app.services.ingestion import fetch_and_store_payment


payment_id = "pay_TVaVDT2HhidoKT"

db = SessionLocal()

try:
    payment = fetch_and_store_payment(db, payment_id)

    print("Payment stored successfully!")
    print("payment_id:", payment.payment_id)
    print("order_id:", payment.order_id)
    print("amount:", payment.amount)
    print("payment_method:", payment.payment_method)
    print("error_code:", payment.razorpay_error_code)
    print("razorpay_state:", payment.razorpay_state)
    print("status:", payment.status)

finally:
    db.close()