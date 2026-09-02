from app.services.razorpay_client import fetch_payment


payment_id = "pay_TVaVDT2HhidoKT"

payment = fetch_payment(payment_id)

print(payment)